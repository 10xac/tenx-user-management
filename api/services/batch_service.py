from fastapi import HTTPException
import pandas as pd
from datetime import datetime
import logging
import traceback
from typing import Dict, List, Optional
import io
import csv
import uuid

# Import all your existing classes and models
from review_scripts.strapi_graphql import StrapiGraphql
from review_scripts.strapi_methods import StrapiMethods
from review_scripts.communication_manager import CommunicationManager
from api.models.trainee import BatchTraineeCreate, TraineeCreate, ConfigInfo, TraineeInfo, BatchConfig
from api.services.trainee_service import TraineeService
from api.services.data_processor import DataProcessor
from api.services.webhook_service import WebhookService
from api.services.email_service import EmailService
from api.core.logging_config import setup_logging
from api.utils.password_generator import generate_secure_password

logger = logging.getLogger(__name__)

class BatchService:
    def __init__(self, batch_create: BatchTraineeCreate):
        self.batch_create = batch_create
        self.config = batch_create.config
        self.file_content = batch_create.file_content
        self.sg = StrapiGraphql(run_stage=self.config.run_stage)
        self.sm = StrapiMethods(run_stage=self.config.run_stage)
        self.cm = CommunicationManager()
        self.data_processor = DataProcessor(self.config)
        self.logger = setup_logging()
        
        # Initialize webhook service if callback_url is provided
        self.webhook_service = WebhookService(self.config) if self.config.callback_url else None
        
        # Initialize email service
        self.sender_email = "train@10academy.org"
        self.email_service = None
        if self.config.admin_email:
            try:
                self.email_service = EmailService(source_email=self.sender_email)
                self.logger.info(
                    f"Email service initialized",
                    extra={
                        'sender_email': self.sender_email,
                        'admin_email': self.config.admin_email,
                        'batch_id': self.config.batch
                    }
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to initialize email service",
                    extra={
                        'sender_email': self.sender_email,
                        'admin_email': self.config.admin_email,
                        'error': str(e)
                    }
                )
        
        # Track created resources for cleanup in case of failure
        self.created_resources = {
            'user_id': None,
            'alluser_id': None,
            'profile_id': None,
            'trainee_id': None
        }

    async def process_batch_trainees(self) -> Dict:
        """Main method to process batch of trainees"""
        start_time = datetime.now()
        self.logger.info(f"Starting batch processing", extra={'batch': self.config.batch})

        try:
            # Process the batch
            results = await self._process_batch_records()
            
            # Send notifications
            await self._send_notifications(results)
            
            # Log completion
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info("Batch processing completed", extra={
                'duration_seconds': duration,
                'batch': self.config.batch,
                'total': results.get('total_processed', 0),
                'successful': results.get('successful', 0),
                'failed': results.get('failed', 0)
            })
            
            return results
            
        except Exception as e:
            error_response = self._create_error_response(e)
            self.logger.error("Batch processing failed", extra={
                'error': str(e),
                'traceback': traceback.format_exc()
            })
            
            # Ensure we still send notifications even on error
            try:
                await self._send_notifications(error_response)
            except Exception as notify_error:
                self.logger.error("Failed to send error notifications", extra={
                    'error': str(notify_error)
                })
            
            return error_response

    async def _process_batch_records(self) -> Dict:
        """Process all records in the batch"""
        try:
            # Read and validate CSV
            df = self._read_csv_file()
            if isinstance(df, dict) and 'error' in df:
                return df
                
            if len(df) == 0:
                return {
                    'status': 'completed',
                    'total_processed': 0,
                    'successful': 0,
                    'failed': 0,
                    'successful_trainees': [],
                    'failed_trainees': []
                }

            if isinstance(df, dict):
                return df

            total = len(df)
            successful = []
            failed = []
            
            # Process each record
            for index, row in df.iterrows():
                try:
                    row_num = index + 1
                    result = await self._process_trainee_record(row, row_num)
                    
                    if result.get('status') == 'Success':
                        successful.append(result)
                    else:
                        failed.append({
                            'name': row.get('name', 'Unknown'),
                            'email': row.get('email', 'Unknown'),
                            'status': 'Failed',
                            'error_type': result.get('error_type', 'PROCESSING_ERROR'),
                            'error_message': result.get('error_message', 'Email or Username already exists')
                        })
                except Exception as e:
                    self.logger.error("Error processing trainee record", extra={
                        'row': index + 1,
                        'error': str(e),
                        'row_data': row.to_dict()
                    })
                    failed.append({
                        'name': row.get('name', 'Unknown'),
                        'email': row.get('email', 'Unknown'),
                        'status': 'Failed',
                        'error_type': 'PROCESSING_ERROR',
                        'error_message': str(e)
                    })

            return self._compile_results(total, successful, failed)

        except Exception as e:
            self.logger.error("Error in batch record processing", extra={
                'error': str(e),
                'batch': self.config.batch
            })
            return self._create_error_response(e)

    async def _process_trainee_record(self, row: pd.Series, row_num: int) -> Dict:
        """Process a single trainee record"""
        try:
            row_data = row.to_dict()
            processed_data = self._process_row_data(row_data)
            
            # Validate required fields
            if not processed_data['name'] or not processed_data['email']:
                raise ValueError("Name and email are required fields")
            
            
            # Create trainee
            trainee_create = TraineeCreate(
                config=ConfigInfo(
                    run_stage=self.config.run_stage,
                    batch=str(self.config.batch),
                    role=self.config.role,
                    group_id=self.config.group_id,
                    is_mock=self.config.is_mock,
                    login_url=self.config.login_url
                ),
                trainee=TraineeInfo(**{
                    'name': processed_data['name'],
                    'email': processed_data['email'],
                    'password': processed_data['password'],
                    'status': processed_data.get('status', 'Accepted'),
                    'nationality': processed_data.get('nationality', ''),
                    'gender': processed_data.get('gender', ''),
                    'date_of_birth': processed_data.get('date_of_birth'),
                    'vulnerable': processed_data.get('vulnerable', ''),
                    'city_of_residence': processed_data.get('city_of_residence', ''),
                    'bio': processed_data.get('bio', ''),
                    'other_info': processed_data.get('other_info', {})
                })
            )

            # Create trainee via service
            trainee_service = TraineeService(trainee_create)
            result = trainee_service.create_trainee_services()  # Remove await since it's synchronous
            
            if result.get('success'):
                # If real user, send welcome email
                # Disabled for now not allowed to send emails to trainees
                # if not self.config.is_mock:
                #     await self.email_service.send_trainee_welcome_email(
                #         email=processed_data['email'],
                #         username=processed_data['email'],
                #         password=password,
                #         login_url=self.config.login_url
                #     )
                
                return {
                    'name': processed_data['name'],
                    'email': processed_data['email'],
                    'password': processed_data['password'] if self.config.is_mock else None,
                    'status': 'Success'
                }
            else:
                return {
                    'name': processed_data['name'],
                    'email': processed_data['email'],
                    'password': processed_data['password'] if self.config.is_mock else None,
                    'status': 'Failed',
                    'error_type': result.get('error', {}).get('error_type', 'PROCESSING_ERROR'),
                    'error_message': result.get('error', {}).get('error_message', 'Email or Username already exists')
                }
        except Exception as e:
            return {
                'name': row_data.get('name', ''),
                'email': row_data.get('email', ''),
                'password': None,
                'status': 'Failed',
                'error_type': 'PROCESSING_ERROR',
                'error_message': str(e)
            }

    # def _generate_password(self, email: str) -> str:
    #     """Generate password based on config options"""
    #     if self.config.password_option == "default":
    #         return self.config.default_password or "10academy"
    #     elif self.config.password_option == "auto":
    #         return str(uuid.uuid4())[:8]  # Generate random 8-character password
    #     else:  # "provided"
    #         return email  # Use email as password

    def _read_csv_file(self) -> pd.DataFrame:
        """Read and validate CSV file"""
        try:
            bytes_io = io.BytesIO(self.file_content)
            df = pd.read_csv(
                bytes_io,
                delimiter=self.config.delimiter,
                encoding=self.config.encoding
            )
            df.columns = df.columns.str.strip()

            # Validate required columns
            required_columns = {'name', 'email'}
            missing = required_columns - set(df.columns)
            if missing:
                error_msg = f'Missing required columns: {missing}'
                self.logger.error("CSV validation failed", extra={
                    'error': error_msg,
                    'batch': self.config.batch
                })
                return {
                    'status': 'failed',
                    'error': error_msg,
                    'error_type': 'VALIDATION_ERROR',
                    'batch': self.config.batch,
                    'total_processed': 0,
                    'successful': 0,
                    'failed': 0,
                    'failed_trainees': []
                }
            
            # Check for empty required fields
            empty_mask = df['name'].isna() | df['email'].isna() | (df['name'] == '') | (df['email'] == '')
            invalid_rows = df[empty_mask]
            if not invalid_rows.empty:
                error_msg = f'Empty required fields in rows: {invalid_rows.index.tolist()}'
                self.logger.error("CSV validation failed", extra={
                    'error': error_msg,
                    'batch': self.config.batch
                })
                return {
                    'status': 'failed',
                    'error': error_msg,
                    'error_type': 'VALIDATION_ERROR',
                    'batch': self.config.batch,
                    'total_processed': 0,
                    'successful': 0,
                    'failed': 0,
                    'failed_trainees': []
                }
            
            return df
            
        except Exception as e:
            self.logger.error("Failed to read CSV file", extra={
                'error': str(e),
                'batch': self.config.batch
            })
            return self._create_error_response(e)

    def _process_row_data(self, row_data: Dict) -> Dict:
        """Process and clean row data"""
        processed = {
            'name': str(row_data.get('name', '')).strip(),
            'email': str(row_data.get('email', '')).strip().lower()
        }
        
        # Handle password: use from CSV if provided, otherwise use email
        csv_password = row_data.get('password')
        if csv_password and not pd.isna(csv_password):
            processed['password'] = str(csv_password).strip()
        else:
            processed['password'] = processed['email']  # Use email as password if no password provided
        
        # Process optional fields
        optional_fields = [
            'nationality', 'gender', 'date_of_birth', 
            'vulnerable', 'bio', 'city_of_residence'
        ]
        
        for field in optional_fields:
            value = row_data.get(field)
            processed[field] = '' if pd.isna(value) else str(value).strip()
        
        # Add metadata
        processed.update({
            'role': self.config.role or 'trainee',
            'batch_id': self.config.batch,
            'groups': [self.config.group_id] if self.config.group_id else [],
            'status': 'Accepted'
        })
        
        # Separate other info
        essential_fields = ['name', 'email', 'nationality', 'gender', 'date_of_birth', 'password',
                          'vulnerable', 'bio', 'city_of_residence', 'role', 'is_mock',
                          'batch_id', 'groups', 'status']
        processed['other_info'] = {
            k: v for k, v in row_data.items() 
            if k not in essential_fields
        }
        
        return processed

    def _compile_results(self, total: int, successful: List, failed: List) -> Dict:
        """Compile final results"""
        status = 'completed' if not failed else 'partial_success' if successful else 'failed'
        
        return {
            'status': status,
            'total_processed': total,
            'successful': len(successful),
            'failed': len(failed),
            'successful_trainees': successful,
            'failed_trainees': failed,
            'batch': self.config.batch,
            'timestamp': datetime.now().isoformat(),
            'metadata': {
                'run_stage': self.config.run_stage,
                'role': self.config.role,
                'group_id': self.config.group_id
            }
        }

    def _create_error_response(self, error: Exception) -> Dict:
        """Create error response for batch failures"""
        return {
            'status': 'failed',
            'error_type': 'BATCH_PROCESSING_ERROR',
            'error_message': str(error),
            'batch': self.config.batch,
            'timestamp': datetime.now().isoformat(),
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'failed_trainees': [{
                'name': 'Batch Error',
                'email': 'N/A',
                'status': 'Failed',
                'error_type': 'BATCH_PROCESSING_ERROR',
                'error_message': str(error)
            }],
            'metadata': {
                'run_stage': self.config.run_stage,
                'role': self.config.role,
                'group_id': self.config.group_id
            }
        }

    async def _send_notifications(self, results: Dict) -> None:
        """Send email and webhook notifications"""
        try:
            # Always try to send webhook notification first if configured
            if self.webhook_service:
                try:
                    await self.webhook_service.notify_callback(results)
                    self.logger.info(
                        "Webhook notification sent successfully",
                        extra={
                            'notification_type': 'webhook',
                            'receiver_url': self.config.callback_url,
                            'batch_id': self.config.batch,
                            'status': results.get('status')
                        }
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to send webhook notification",
                        extra={
                            'notification_type': 'webhook',
                            'receiver_url': self.config.callback_url,
                            'batch_id': self.config.batch,
                            'error': str(e)
                        }
                    )
            
            # Always try to send admin email if configured
            if self.email_service and self.config.admin_email:
                try:
                    # Prepare error details for failed trainees
                    error_details = []
                    failed_trainees = results.get('failed_trainees', [])
                    
                    for trainee in failed_trainees:
                        error_details.append({
                            'email': trainee.get('email', 'Unknown'),
                            'name': trainee.get('name', 'Unknown'),
                            'reason': f"{trainee.get('error_type', 'Unknown Error')}: {trainee.get('error_message', 'No message')}"
                        })
                    
                    # Prepare successful trainee details with credentials if mock mode
                    successful_details = []
                    successful_trainees = results.get('successful_trainees', [])
                    
                    for trainee in successful_trainees:
                        trainee_info = {
                            'email': trainee.get('email', 'Unknown'),
                            'name': trainee.get('name', 'Unknown'),
                            'status': 'Success'
                        }
                        if self.config.is_mock:
                            trainee_info['credentials'] = {
                                'username': trainee.get('email'),
                                'password': trainee.get('password')
                            }
                        successful_details.append(trainee_info)
                    
                    # Create the processing status detail with the correct structure
                    processing_status_detail = {
                        "admin_email": self.config.admin_email,
                        "batch_id": self.config.batch,
                        "total": results.get('total_processed', 0),
                        "successful": results.get('successful', 0),
                        "failed": results.get('failed', 0),
                        "error_details": error_details,
                        "successful_details": successful_details,
                        "is_mock": self.config.is_mock,
                        "successful_trainees": successful_trainees,
                        "failed_trainees": failed_trainees
                    }
                    
                    # Create and send CSV email with the correct structure
                    csv_content = self._create_summary_csv(
                        successful_details,
                        error_details
                    )
                    
                    # Send the email with the properly structured data
                    await self.email_service.send_batch_csv_email(
                        admin_email=self.config.admin_email,
                        batch_id=self.config.batch,
                        results=processing_status_detail,
                        csv_content=csv_content
                    )
                    
                    self.logger.info(
                        f"Admin summary and CSV emails delivered",
                        extra={
                            'notification_type': 'admin_summary',
                            'sender': self.sender_email,
                            'receiver': self.config.admin_email,
                            'batch_id': self.config.batch,
                            'status': 'delivered',
                            'processing_status': results.get('status'),
                            'is_mock': self.config.is_mock
                        }
                    )
                    
                    # Only send welcome emails for successful trainees
                    successful_trainees = results.get('successful_trainees', [])
                    if successful_trainees:
                        self.logger.info(
                            f"Starting trainee welcome emails",
                            extra={
                                'notification_type': 'trainee_welcome',
                                'sender': self.sender_email,
                                'batch_id': self.config.batch,
                                'trainee_count': len(successful_trainees)
                            }
                        )
                        
                        # Send welcome emails to successful trainees Disabled for now not allowed to send emails to trainees
                        # for trainee in successful_trainees:
                        #     if trainee.get('email'):
                        #         try:
                        #             await self.email_service.send_trainee_welcome_email(
                        #                 email=trainee['email'],
                        #                 username=trainee['email'],
                        #                 password=trainee.get('password', trainee['email']),
                        #                 login_url=self.config.login_url
                        #             )
                                    
                        #             self.logger.info(
                        #                 f"Trainee welcome email delivered",
                        #                 extra={
                        #                     'notification_type': 'trainee_welcome',
                        #                     'sender': self.sender_email,
                        #                     'receiver': trainee['email'],
                        #                     'batch_id': self.config.batch,
                        #                     'status': 'delivered'
                        #                 }
                        #             )
                        #         except Exception as e:
                        #             self.logger.error(
                        #                 f"Failed to send trainee welcome email",
                        #                 extra={
                        #                     'notification_type': 'trainee_welcome',
                        #                     'sender': self.sender_email,
                        #                     'receiver': trainee['email'],
                        #                     'batch_id': self.config.batch,
                        #                     'error': str(e)
                        #                 }
                        #             )
                                
                except Exception as e:
                    self.logger.error(
                        f"Failed to send admin emails",
                        extra={
                            'notification_type': 'admin_summary',
                            'sender': self.sender_email,
                            'receiver': self.config.admin_email,
                            'batch_id': self.config.batch,
                            'error': str(e)
                        }
                    )
            else:
                self.logger.warning(
                    "Email notifications skipped",
                    extra={
                        'reason': 'Email service not initialized' if not self.email_service else 'Admin email not provided',
                        'admin_email': self.config.admin_email,
                        'batch_id': self.config.batch
                    }
                )
                    
        except Exception as e:
            self.logger.error(
                f"Error in notification process",
                extra={
                    'batch_id': self.config.batch,
                    'sender': self.sender_email,
                    'error': str(e),
                    'notification_config': {
                        'webhook_url': self.config.callback_url if self.webhook_service else None,
                        'admin_email': self.config.admin_email if self.email_service else None
                    }
                }
            )

    def _cleanup_resources(self, error_step: str) -> None:
        """Clean up created resources in case of failure"""
        try:
            if error_step == 'alluser' and self.created_resources['user_id']:
                self.cm.delete_user(self.sg, self.created_resources['user_id'])
                
            elif error_step == 'profile':
                if self.created_resources['alluser_id']:
                    self.cm.delete_alluser(self.sg, self.created_resources['alluser_id'])
                if self.created_resources['user_id']:
                    self.cm.delete_user(self.sg, self.created_resources['user_id'])
                    
            elif error_step == 'trainee':
                if self.created_resources['trainee_id']:
                    self.cm.delete_trainee(self.sg, self.created_resources['trainee_id'])
                if self.created_resources['profile_id']:
                    self.cm.delete_profile(self.sg, self.created_resources['profile_id'])
                if self.created_resources['alluser_id']:
                    self.cm.delete_alluser(self.sg, self.created_resources['alluser_id'])
                if self.created_resources['user_id']:
                    self.cm.delete_user(self.sg, self.created_resources['user_id'])
        except Exception as e:
            logger.error("Error during resource cleanup", extra={
                'error_step': error_step,
                'error': str(e)
            })

    def _create_summary_csv(self, successful_trainees: List[Dict], failed_trainees: List[Dict]) -> bytes:
        """Create CSV file with trainee summary"""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        if self.config.is_mock:
            writer.writerow(["Name", "Email", "Password", "Status", "Error Message"])
        else:
            writer.writerow(["Name", "Email", "Status", "Error Message"])
        
        # Write successful trainees
        for trainee in successful_trainees:
            if self.config.is_mock:
                writer.writerow([
                    trainee.get('name', ''),
                    trainee.get('email', ''),
                    trainee.get('password', ''),
                    "Success",
                    ""
                ])
            else:
                writer.writerow([
                    trainee.get('name', ''),
                    trainee.get('email', ''),
                    "Success",
                    ""
                ])
        
        # Write failed trainees
        for trainee in failed_trainees:
            if self.config.is_mock:
                writer.writerow([
                    trainee.get('name', ''),
                    trainee.get('email', ''),
                    trainee.get('password', ''),
                    "Failed",
                    trainee.get('error_message', 'Email or Username already exists')
                ])
            else:
                writer.writerow([
                    trainee.get('name', ''),
                    trainee.get('email', ''),
                    "Failed",
                    trainee.get('error_message', 'Email or Username already exists')
                ])
        
        # Get the CSV content and encode it
        csv_content = output.getvalue()
        output.close()
        
        return csv_content.encode('utf-8')

    