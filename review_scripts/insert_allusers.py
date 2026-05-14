
import json
import os
import sys
import datetime
import numpy as np
import pandas as pd
import uuid

from review_scripts.strapi_graphql import StrapiGraphql
from review_scripts.strapi_methods import StrapiMethods
from utils.question_mapper import column_mapper
from review_scripts.communication_manager import CommunicationManager
from utils.gdrive import gsheet

class InsertAllUsers:
    def __init__(self, run_stage="dev-cms", 
                 sid_application="17XDDjWzPXJ-mmkWAFVz5IMpsVfmFyKtvXOJ6YwqS3CM", 
                 batch="batch-6",
                 sname = 'forBackendUse', role="trainee") -> None:
        self.sid_application = sid_application
        self.batch = batch
        self.cm = CommunicationManager()
        self.sm = StrapiMethods(run_stage=run_stage)
        self.sg = StrapiGraphql(run_stage=run_stage)
        self.role = role # applicant, trainee, staff
        self.sname= sname
        

    
    def get_staff_data(self):
        """
        Function to read staff data from specified sheet from google sheet. 
        Args: 
            sid_application: sheet id for the staff information 
        Returns:
            df: dataframe
        """


        if self.sid_application:
            gd = gsheet(sheetid=self.sid_application,
                        fauth='admin-10ac-service.json')
        else:

            gd = gsheet(sheetid="1mG8uNDxaDfNq-iRi-_-mgsz5rArkrMPAXtV8IR53xXM",
                    fauth='admin-10ac-service.json')
   

        try:
            df = gd.get_sheet_df(self.sname)

            # print(df.head())
            print(f'------------{self.sname} df.shape={df.shape}----')

        except Exception as e:
            print(f'ERROR: Could not obtain sheet for {self.sname}', e)

        return df

    def insert_user(self, user_data):
        """
        A function to insert user data into the database.

        Parameters:
            user_data (dict): A dictionary containing user data with keys 'email' and 'name'.

        Returns:
            int: The user ID of the newly created user.
        """
        result_json = self.cm.create_user(self.sg, user_data)
        try:
            user_id = result_json['data']['register']['user']['id']
        except:
            print("ERROR: Could not create user....................", user_data)
            user_id = 0
       
        return  user_id 

    def get_applicant_data(self):
        """
        Function to read application from google sheet. 
        Args: 
            sid_application: sheet id for the application information 
        Returns:
            df: dataframe
        """

        gd = gsheet(sheetid=self.sid_application,
                    fauth='admin-10ac-service.json')
    

        try:
            df = gd.get_sheet_df(self.sname)

            # print(df.head())
            print(f'------------{self.sname} df.shape={df.shape}----')

        except Exception as e:
            print(f'ERROR: Could not obtain sheet for {self.sname}', e)

        return df

    def change_name_fullname(self, row):
        """
        Function to change names to full name . 
        Args: 
            row: row containes first name and last name
        Returns:
            fname: returns full name
        """
        fname = row['firstname'].strip().title()
        lname = row['familyname'].strip().title()
        lenstring = fname.split(" ")
        lname_words = lname.split(" ")
        if len(lenstring) < 2:
            fullname = fname+" "+lname_words[0]
            return fullname
        else:
            return fname

    def process_dataframe(self):

        """
        Function to preprocess trainee information  
       
        Returns:
            df: dataframe
        """

        app_df = self.get_applicant_data()
        df = app_df.T
        # df['Timestamp'] = df['Timestamp'].apply(
        #     lambda x: datetime.datetime.strptime(x, "%d/%m/%Y %H:%M:%S"))

        df['Batch'] = self.batch

        columns = df.columns.to_list()
        for cols in columns:
            db_col = column_mapper(cols)
            df.rename(columns={cols: db_col}, inplace=True)
        df = df.replace(r'^\s+$', np.nan, regex=True)

        # df['Name'] = df.apply(lambda x: self.change_name_fullname(x), axis=1)
        df['Name'] = df['Name'].apply(lambda x: x.strip().title())
        ## remove -. from name in df 
        df['Name'] = df['Name'].apply(lambda x: x.replace('-', '').replace('.', '').replace('  ', ' '))

        df['Email'] = df['Email'].apply(lambda x: x.strip().lower())
        return df

    def prepare_applicants(self):

        df = self.process_dataframe()
        df = df.replace('', 'null')
      

        user_df = df[['Email', 'Name', 'Country', 'gender']]
        user_df.rename(columns={'Name': 'name', 'Email': 'email'}, inplace=True)
        user_df['role'] = "applicant"
        user_df['Batch'] = int(df['batch'][1].split("-")[1])
        return user_df

    def process_user_and_alluser_insertion(self):
        df = self.prepare_applicants()
        df =  df[48:]
        for i, row in df.iterrows():
            res_dict = {
                "name": row['name'],
                "email": row['email'],
                "role": row['role'],
                "batch": row['Batch'],
            }
            userId = self.insert_user( row)
            if userId == 0:
                continue
            res_dict['userId']= userId
            res = self.cm.insert_all_users(res_dict)
            print(res)
        print ("All recored hase been inserted successfully")
    
    

    def select_users_from_allusers(self):
        """
        Function to preprocess trainee information  
       
        Returns:
            df: dataframe
        """
      
        batch = int(self.batch.split("-")[1])
        req_params = {"batch":batch, "role":self.role}
        result_json = self.cm.read_all_users(self.sg, req_params)
        df = pd.json_normalize(result_json['data']['allUsers']['data'])
        df.rename(columns={"attributes.name": "name", "attributes.email": "Email",
                    "attributes.Batch": "batches", 'id':'all_user'}, inplace=True)
       
        df = df.drop(columns=['name'])
        return df




    def insert_reviewers(self):
        """
        Function to insert users to reviewers table. 
        
        Returns:
           
        """
        batch = self.get_batch()
        df =self.select_users_from_allusers()
        df.rename(columns={'id':'all_user','Batch':'batches','email':'Email'}, inplace=True)
        df= df[['all_user', 'Email']]
    
        df['batches']= batch


        for i, row in df.iterrows():
            res = self.cm.create_reviewer(self.sg, row)
            print(res)
        # table = f"https://{self.root}.10academy.org/api/reviewers"
        # result = df.to_json(orient="records", date_format='iso')
        

        # for data in json.loads(result):
        #     print(data)
        #     r = self.sm.insert_data(data, table, self.sm.token['token'])
        #     print(r)
            # break
        print("All records are inserted")


    def insert_group(self):
        """
        Function to insert users to group table. 
        
        Returns:
           
        """

        adf =self.select_users_from_allusers()
   
        adf.rename(columns={'all_user':'all_users','name':'Name'}, inplace=True)
        ids = adf['all_users'].to_list()
  
        table = "groups"
        # table = f"https://{self.root}.10academy.org/api/groups"
      
        batch_name = "B"+str(self.batch.split("-")[1])#+ "-"+ "w0"
        data={'Name':batch_name,'all_users':ids}

        r = self.sm.insert_data(data, table)
        print(r)
    
######################################################### for Trainees with review 
    def get_quiz_result(self, sid_quiz):

        gd = gsheet(sheetid=sid_quiz, fauth='admin-10ac-service.json')
        sname = f'Form responses 1'

        try:
            df = gd.get_sheet_df(sname)

            # print(df.head())
            # print(f'------------{sname} df.shape={df.shape}----')

        except Exception as e:
            print(f'ERROR: Could not obtain sheet for {sname}', e)

        return df

    def process_quiz(self):

        score_df = self.get_quiz_result(
            "1EWnob10WYkHi0Sn87u5EqiVz7_JWCYzW92bIj_hn8EA")
        transform = score_df.T
        transform.rename(columns={"Email address: please ensure that you use the same email address as you used on your 10 Academy Batch 6 application.  Using a different email address will make it much more difficult for us to assign this result to you.": 'email'}, inplace=True)

        applicant_df = self.select_applicants_from_allusers()

        applicant_df.rename(
            columns={'attributes.email': 'email'}, inplace=True)

        transform['email'] = transform['email'].str.strip()
        transform['eamil'] = transform['email'].str.lower()

        all_info_df = pd.merge(transform, applicant_df, on="email", how="left")
        clean_df = all_info_df[['Score', 'email', 'id']]
        clean_df['Score'] = clean_df['Score'].apply(
            lambda x: int(x.split("/")[0].strip()))

        # post_process = clean_df.dropna()
        return clean_df
    
    def chunck_reviews(self, df):
        
        total_applicant= len (df)
        reviwe_size = round(total_applicant/4)
        dfs = {}
        for n in range((df.shape[0] // reviwe_size + 1)):
            if n ==3:
                df_temp = df.iloc[n*reviwe_size:(n+3)*reviwe_size]
                df_temp = df_temp.reset_index(drop=True)
                dfs[n] = df_temp
            else:
                df_temp = df.iloc[n*reviwe_size:(n+1)*reviwe_size]
                df_temp = df_temp.reset_index(drop=True)
                dfs[n] = df_temp
           
            
        return dfs
    
    def filter_application (self):
        graduation = "When is your graduation date? Put your expected graduation date if you are still studying (Note: Applicants whose graduation date is between 1 Jan 2022 and 30 April 2022 are likely to be prioritized - a proof will be asked for at a later stage of the process)"
        applicant_df = self.select_applicants_from_allusers()

        app_df = self.get_applicant_data()  # from Gsheet
        df = app_df.T
       
        df['Timestamp'] = df['Timestamp'].apply(
            lambda x: datetime.datetime.strptime(x, "%d/%m/%Y %H:%M:%S"))
        df['Year'] = df['Timestamp'].dt.year
        reason = 'I agree that 10 Academy can use my application information for processing my application and for keeping me informed of further opportunities in related fields. We will not share/sell your information. Our full terms and conditions are here: https://docs.google.com/document/d/1yduZ66dH5o8vA_scA3N6tOla9OeJuhoFRGTQ35KsG0g/edit?usp=sharing and our privacy policy is here: https://docs.google.com/document/d/1jhZqUb2S92UM5wjMzPlRpHew_A5xjkRgLK7gZfpoAik/edit?usp=sharing'
        new_idea = "Imagine you were asked to design and implement a project. The project will use technology (AI, Web3, others) to positively impact at least 5 million people in 5 years in a sustainable (financially, environmentally) and scalable way. Briefly describe the problem you would choose (from any field e.g agriculture, education, etc) and how your solution will be impactful, scalable, and sustainable. Detailed answers are helpful. (1500 characters max)"
        pay_it_forward = "Please confirm that you have read and are in agreement with the costs and pay-it-forward model for 10 Academy Batch 6 "
        obligation = "If you are admitted to 10 Academy's Batch 6 intensive training, are you able to commit full-time (~60 hours/week) without conflicting obligations?"
        self_fund = 'Are you able to self-fund and provide the technical requirements for our remote training?'
        df[graduation] = pd.to_datetime(
            df[graduation], errors='coerce', infer_datetime_format=True)
        df['Date of Birth'] = pd.to_datetime(
            df["Date of Birth"], errors='coerce', infer_datetime_format=True)
        quiz_data = self.process_quiz()
        applicant_with_quiz = pd.merge(
            applicant_df, quiz_data[['Score','email']],  on="email", how="left")

        # Criteria to be filtered
        filtered_df = df[(df[new_idea].str.len() >= 100)]
        filtered_df = filtered_df[(
            filtered_df[pay_it_forward].str.lower() == 'yes')]
        filtered_df = filtered_df[(filtered_df[reason].str.lower() == 'yes')]
        filtered_df = filtered_df[(
            filtered_df[obligation].str.lower() == 'yes')]
        filtered_df = filtered_df[(
            filtered_df[self_fund].str.lower() == 'yes')]

        print("applicant", applicant_df.shape)
        
        new_df = filtered_df.drop_duplicates(
            subset=['Email address', 'First Name(s)/Given Name(s)'], keep='first')

        print("clean", new_df.shape)

        new_df.rename(columns={"Email address": "email"}, inplace=True)
        all_info_df = pd.merge(
            new_df, applicant_with_quiz, on="email", how="left")

        all_info_df['Timestamp'] = all_info_df['Timestamp'].astype(str)
        all_info_df.fillna("null")
        all_info_df.drop(
            columns=['Year', 'name', 'Batch'], inplace=True)
        
        df_selected = all_info_df[((all_info_df['Gender']=="Male") & (all_info_df['Score']>40))|((all_info_df['Gender']=="Female") & (all_info_df['Score']>35)) ]
        print(df_selected.columns)
        return df_selected
    
    
    def insert_1hr_score(self, row):
        """
            Function to insert 1hr test result 
      
         """
        grade_table = f"https://{self.root}.10academy.org/api/grades"
        tosend_grade = {
            "label":"B6 1hr test",
            "score":round(float(row['Score'])),
            
            "all_user":int(row['id'])
            }
        
        r = self.sm.insert_data(tosend_grade,grade_table, self.sm.token['token'])
        grade_id = r['data']['id']
        print(r)
        return grade_id



    def get_reviewers (self):
            """
            Function to get current batch reviewers from strapi graphql
            Args:
                Self.batch (Int): Number that represent current batch 

            Returns:
                reviewers (list): List of reviewers for current batch
            """
            query = """ query getReviewer($batch: Int) {
                    reviewers(
                        pagination: { start: 0, limit: 100 }
                        filters: {
                            reviewer_batch_accesses: {
                                batch: { Batch: { eq: $batch } }
                                hasTenx: { eq: true }
                            }
                        }
                    ) {
                        data {
                        id
                        attributes {
                            Email
                        }
                        }
                    }
                    }
            """
            reviewerJson = self.sg.Select_from_table(query=query, variables={"batch": self.batch})
            
            reviewerdf =  pd.json_normalize(reviewerJson['data']['reviewers']['data'])
            reviewers = reviewerdf['id'].to_list()
            return reviewers


    def process_with_question_type(self):
        """
            Function to used to insert with different chunks and  with question, one hour score 
            Args:
                Self.batch (Int): Number that represent current batch 

            Returns:
                reviewers (list): List of reviewers for current batch
        """
        df_selected = self.filter_application()
        length_cols = df_selected.columns
        # length_cols.remove('Score')
        print(length_cols.delete(-1))
        text_filed = ['Email address', 'First Name(s)/Given Name(s)', 'Family Name(s)/Surname(s)',
                      'City of current residence', 'Field of Study', 'Name of Institution', 'Special academic achievements and honors',
                      'GitHub Profile Link', 'LinkedIn Profile Link', 'Name of Reference',
                      'Work Experience Specifications', 'How many months of full-time work experience do you have as of 30 June 2022?',
                      'Kaggle/Zindi Profile Link', ]

        check_box = ['Work Experience so far if any',
                     'How did you learn about 10 Academy and this program?']
        date = ['Timestamp', 'Date of Birth',
                'When is your graduation date? Put your expected graduation date if you are still studying (Note: Applicants whose graduation date is between 1 Jan 2022 and 30 April 2022 are likely to be prioritized - a proof will be asked for at a later stage of the process)']
        long_text = ['Imagine you were asked to design and implement a project. The project will use technology (AI, Web3, others) to positively impact at least 5 million people in 5 years in a sustainable (financially, environmentally) and scalable way. Briefly describe the problem you would choose (from any field e.g agriculture, education, etc) and how your solution will be impactful, scalable, and sustainable. Detailed answers are helpful. (1500 characters max)',
                     'Why do you want to join 10 Academy Batch 6 Intensive Training? Help our team to understand your past work, your future goals and how your taking up 10 Academy training will help you (and those around you) to grow. (1500 characters max)',
                     'Please describe, in detail, any self-taught or extra-curricular data science-related courses that you have undertaken or completed.']
        
        
        table = f"https://{self.root}.10academy.org/api/reviews/"
       
        response = []
        applicant_list = self.chunck_reviews(df_selected)
        
        for i in applicant_list:
            reviewgroup = applicant_list[i]
        
            if i == 0:
                reviewers = self.get_reviewers()# [8,10,16,11,30,15 ]  # dev tenx 
                for index, row in reviewgroup.iterrows():
                    grade_id = self.insert_1hr_score(row)
                    prefilled_res = []
                    for i in length_cols:
                        if i == 'id':
                            continue
                        elif i in text_filed:
                            dic = {
                                "type": "textbox",
                                "label": i,
                                "answer": str(row[i]),
                                "required": "true"

                            }
                        elif i in long_text:
                            dic = {
                                "type": "textarea",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in date:
                            dic = {
                                "type": "date",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in check_box:
                            dic = {
                                "type": "multi-select",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        else:
                            dic = {
                                "type": "radio",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }

                        prefilled_res.append(dic)
                    
                    to_send = {
                        "status": "Not_reviewed",
                        "prefilled_response": prefilled_res,
                        "all_user": row['id'],
                        "review_category": 6,
                        "reviewers":reviewers,
                        "grade":grade_id
                    }

                    r = self.sm.insert_data(to_send, table, self.sm.token['token'])
                    print(r)
            elif i==1:
                reviewers = self.get_reviewers()#[8,10,16,11,24,28 ] # dev tenx 
                for index, row in reviewgroup.iterrows():
                    grade_id = self.insert_1hr_score(row)
                    prefilled_res = []
                    for i in length_cols:
                        if i == 'id':
                            continue
                        elif i in text_filed:
                            dic = {
                                "type": "textbox",
                                "label": i,
                                "answer": str(row[i]),
                                "required": "true"

                            }
                        elif i in long_text:
                            dic = {
                                "type": "textarea",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in date:
                            dic = {
                                "type": "date",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in check_box:
                            dic = {
                                "type": "multi-select",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        else:
                            dic = {
                                "type": "radio",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }

                        prefilled_res.append(dic)
                    to_send = {
                        "status": "Not_reviewed",
                        "prefilled_response": prefilled_res,
                        "all_user": row['id'],
                        "review_category": 6,
                        "reviewers":reviewers,
                        "grade":grade_id
                    }

                    r = self.sm.insert_data(to_send, table, self.sm.token['token'])
                    print(r)
            elif i==2:
                reviewers =  self.get_reviewers() #[8,10,16,11,26,29 ]  # dev tenx 
                for index, row in reviewgroup.iterrows():
                    grade_id = self.insert_1hr_score(row)
                    prefilled_res = []
                    for i in length_cols:
                        if i == 'id':
                            continue
                        elif i in text_filed:
                            dic = {
                                "type": "textbox",
                                "label": i,
                                "answer": str(row[i]),
                                "required": "true"

                            }
                        elif i in long_text:
                            dic = {
                                "type": "textarea",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in date:
                            dic = {
                                "type": "date",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in check_box:
                            dic = {
                                "type": "multi-select",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        else:
                            dic = {
                                "type": "radio",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }

                        prefilled_res.append(dic)
                    to_send = {
                        "status": "Not_reviewed",
                        "prefilled_response": prefilled_res,
                        "all_user": row['id'],
                        "review_category": 6,
                        "grade":grade_id,
                        "reviewers":reviewers
                    }

                    r = self.sm.insert_data(to_send, table, self.sm.token['token'])
                    print(r)
            elif i==3:
                reviewers =  self.get_reviewers() # [8,10,16,11,21,31 ]   # dev tenx 
                for index, row in reviewgroup.iterrows():
                    grade_id = self.insert_1hr_score(row)
                    prefilled_res = []
                    for i in length_cols:
                        if i == 'id':
                            continue
                        elif i in text_filed:
                            dic = {
                                "type": "textbox",
                                "label": i,
                                "answer": str(row[i]),
                                "required": "true"

                            }
                        elif i in long_text:
                            dic = {
                                "type": "textarea",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in date:
                            dic = {
                                "type": "date",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        elif i in check_box:
                            dic = {
                                "type": "multi-select",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }
                        else:
                            dic = {
                                "type": "radio",
                                "label": i,
                                "answer": str(row[i]),

                                "required": "true"

                            }

                        prefilled_res.append(dic)
                    to_send = {
                        "status": "Not_reviewed",
                        "prefilled_response": prefilled_res,
                        "all_user": row['id'],
                        "review_category": 6,
                        "grade":grade_id,
                        "reviewers":reviewers
                    }

                    r = self.sm.insert_data(to_send, table, self.sm.token['token'])
                    print(r)
  
        return df_selected




    ########################################################
    ### Insertion of profile information 
    
    def extract_last_name(self, name):
        parts = name.split()
        # Return everything except the first part
        return ' '.join(parts[1:]) if len(parts) > 1 else ''


    def process_profile_information_insertion(self):
        df = self.prepare_applicants()
        adf = self.select_users_from_allusers()
        adf.rename(columns={"Email":"email"}, inplace=True)
        ddf =  df.merge(adf, on="email", how="left")
        ddf['role'] = "trainee"

        ddf['last_name'] = ddf['name'].apply(self.extract_last_name)

        ddf['first_name'] = ddf['name'].str.split(' ').str[0]

        for i, row in ddf.iterrows():
            print("processing..................", row['email'])
            dict_res = {
                "firstName": row['first_name'],
                "surName": row['last_name'],
                "nationality": row['Country'],
                "gender": row['gender'],
                "email": row['email'],
                "alluser": row['all_user']
                    }
            res = self.insert_profile_information(dict_res)
            print(res)
        print("All records have been inserted successfully")



    ###################################################################
    ### To insert traineees
    def get_batch (self):
        """
            Function to get current batch from strapi graphql

        Args:
            Self.batch (Int): Number that represent current batch 

        Returns:
            Strapi Id of the imputed batch 
        """
        
        batch = int(self.batch.split("-")[1])
        print(batch )
        batch_json = self.cm.read_batch_information(self.sg, {'batch': batch})
      
        batchdf =  pd.json_normalize(batch_json['data']['batches']['data'])
        batch  = batchdf[batchdf['attributes.Batch']==batch]
        return int(batch['id'])
    
    def generate_uuid(self):
        """Generate a unique UUID."""
        uuid_value = uuid.uuid4()

        return str( uuid_value )
    
    def process_for_trainee_submission(self):
        batch = self.get_batch()
        adf = self.select_users_from_allusers()
        adf.rename(columns={"Email":"email"}, inplace=True)
        adf = adf[['all_user','email']]
 
        adf['batch'] =  str(batch)
        ### create UUID for all trainee
        adf['trainee_id'] = adf['email'].apply(lambda x: self.generate_uuid())
        adf['Status'] ="Accepted"
        
        print("INFO:Total number of newly accepted with trainee ",adf.shape)
        result = adf.to_json(orient="records", date_format = 'iso')
        
        url = f"https://{self.root}.10academy.org/api/trainees"

        for single in json.loads(result):
            print(single)
            r= self.sm.insert_data(single,url,self.sm.token['token'])
            print(r)

        print("All records have been inserted successfully")
        

 


       
    ####################
    def get_batch_specific_reviewers(self):
        """
            Function to get current batch from strapi graphql

        Args:
            Self.batch (Int): Number that represent current batch 

        Returns:
            Strapi Id of the imputed batch 
        """
        bquery = """

            query getReviewer($batch: Int) {
                    reviewers(
                        pagination: { start: 0, limit: 100 }
                        filters: {
                            reviewer_batch_accesses: {
                                batch: { Batch: { eq: $batch } }
                                hasTenx: { eq: true }
                            }
                        }
                    ) {
                        data {
                        id
                        attributes {
                            Email
                        }
                        }
                    }
                    }
            """
        batch = int(self.batch.split("-")[1])
        print(batch)
        # batch =  str(batch)
        batchJson = self.sg.Select_from_table(query=bquery, variables={"batch": batch})
        return batchJson
