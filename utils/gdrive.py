from __future__ import print_function
import os, sys
import pickle
import os.path
import json
from utils.secret import ENVDIR


import numpy as np
import pandas as pd

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2 import service_account


from utils.secret import get_auth

#https://developers.google.com/classroom/guides/auth
class gauth():
    guser = 'service'

    if guser=='service':
        fauth = 'admin-10ac-service.json'
        ftoken = 'admin_service_token.pickle'
        user_email = 'yabebal@10academy.org'
    else: 
        fauth = 'admin-10ac-oauth.json'
        ftoken = 'admin_oauth_token.pickle'
        user_email = None
        
class google_api():
    
    def __init__(self, 
                 token_file='token.pickle',
                 fauth='admin-10ac-service.json', 
                 SCOPES=None,
                 user_email=None,
                 verbose=1):
        
        if SCOPES is None:
            #reference: https://developers.google.com/classroom/guides/auth
            self.SCOPES = [
                #with ability to use files/images stored in drive
                'https://www.googleapis.com/auth/drive',
                #to edit slides
                'https://www.googleapis.com/auth/presentations',
                #to sheet
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                #ref: 
                #https://developers.google.com/admin-sdk/reports/v1/appendix/usage/customer
                #https://developers.google.com/admin-sdk/reports/reference/rest/v1/customerUsageReports/get
                'https://www.googleapis.com/auth/admin.reports.usage.readonly',
                #ref: 
                #https://developers.google.com/admin-sdk/reports/v1/updated-meet-metrics
                #https://developers.google.com/admin-sdk/reports/v1/quickstart/python
                'https://www.googleapis.com/auth/admin.reports.audit.readonly'
            ]
            root = 'https://www.googleapis.com/auth/'
            scopes = (
                "classroom.student-submissions.students.readonly",
                "classroom.profile.emails",
                "classroom.courses",
                "classroom.rosters",
                "classroom.profile.photos"
                 )
            scopes = list((root+e for e in scopes))
            self.SCOPES += scopes
        
        else:
            self.SCOPES = SCOPES
        
        #
        self.verbose = verbose
        
        #get credential file
        self.HOME = os.environ.get('HOME','~')
        
        if fauth is None:
            fauth = 'gclass_credentials.json'

        # use .envdir for credentials to align with new cache approach
        path = os.path.expanduser(ENVDIR)
        os.makedirs(path, exist_ok=True)
        self.fauth = os.path.join(path, fauth)

        self.token_file = os.path.join(path, 'gtoken', token_file)
        #print('token file',self.token_file)
        
        if self.verbose>1:
            print(f'fauth={self.fauth}')
            print(f'token_file={self.token_file}')

        if not os.path.exists(self.fauth):
            auth = get_auth(ssmkey='gspread/config',
                            envvar='GSPREAD_CONFIG',
                            write_to_path=self.fauth)
        else:
            auth = json.load(open(self.fauth,'r'))
       
            
        if auth.get("type",'')=="service_account":
            print(f'****** using service account: {self.fauth}')
            self.creds = self.get_service_account()
            if user_email:
                print(f'delegating user: {user_email}')
                self.creds = self.creds.with_subject(user_email)
            else:
                print('service account is being used without delegation..')
                
        else:
            self.creds = self.get_token()

    def get_service_account(self):
        return (service_account.Credentials \
                    .from_service_account_file(self.fauth,scopes=self.SCOPES))
        
    def get_token(self):
        """Shows basic usage of the Slides API.
        Prints the number of slides and elments in a sample presentation.
        """
        creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        
        if os.path.exists(self.token_file):
            print(f'reading .. {self.token_file}')
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        else:
            print(f'{self.token_file} does not exist .. generating new token')

        
        # If there are no (valid) credentials available, let the user log in.
        if creds is None  or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print('auth, scope:',self.fauth, self.SCOPES)
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.fauth, self.SCOPES)
                creds = flow.run_local_server(port=0) #,open_browser=False
                
            # Save the credentials for the next run
            with open(self.token_file, 'wb') as token:
                print(f'token written to {self.token_file}')
                pickle.dump(creds, token)

        return creds
    
    def get_service(self,name=['drive','sheet','slide','class','admin']):
        
        s = {}            
        if 'sheet' in name: 
            s['sheet'] = build('sheets', 'v4', credentials=self.creds)
            
        if 'drive' in name:        
            s['drive'] =  build('drive',  'v3', credentials=self.creds)
            
        if 'slide' in name:
            s['gslide'] = build('slides', 'v1', credentials=self.creds)
            
        if 'class' in name:
            s['class'] = build('classroom', 'v1', credentials=self.creds)
            
        if 'admin' in name:
            #https://developers.google.com/admin-sdk
            s['admin'] = build('admin', 'reports_v1', credentials=self.creds)
            
        
        return s
    

class gsheet(google_api):
    
    def __init__(self,sheetid, 
                 ftoken = 'token.pickle',
                 fauth = None,
                 sheetname = None):        
        
        
        super().__init__(fauth = fauth, token_file = ftoken)
        #print(ftoken, type(ftoken))
        #
        self.sheetid = sheetid
        self.sheetname = sheetname
        
        s = self.get_service()
        self.drive = s['drive'] 
        self.gsheet = s['sheet'] 
        
        self.sheet = self.gsheet.spreadsheets()
       

    def get_sheet_df(self,name, start='A',
                     end=None, iheader=0, idata=0, lastrow=0,    
                     major='COLUMNS'):  
        
        #get header
        if iheader>0:
            hrange = f'{name}!{start}{iheader}:{end}{iheader}'
            result = self.sheet.values().get(spreadsheetId=self.sheetid, 
                                                    range=hrange).execute()
            if idata==1:
                idata=2            
            self.all_columns = result.get('values', [])[0]
        else:
            iheader=0
            nrows = lastrow-idata+1
            self.all_columns=['']*nrows
            
        
        
        #get data
        if lastrow==0:
            drange = f'{name}'
            if idata>0:
                drange += f'!{start}{idata}'
                
            if end is not None:
                drange += f':{end}'              
                
        else:
            drange = f'{name}!{start}{idata}:{end}{lastrow}'

        result = self.sheet.values().get(spreadsheetId=self.sheetid, 
                                         range=drange,
                                         majorDimension=major).execute()
         
        values = result['values']

        if lastrow==0:
            df = pd.DataFrame(values).transpose()
            col = df.iloc[0].values
            df = df.drop([0])
            df.columns = col
        else:
            nrows = lastrow-idata+1
            data = {col:['']*nrows for col in self.key_columns}
            for col in self.key_columns:
                if col in self.all_columns:
                    ic = self.all_columns.index(col)
                    v = values[ic]
                    nv = len(v)
                    data[col][0:nv] = v
                        
            df = pd.DataFrame.from_dict(data)
        

        #df = df[:,self.key_columns].dropna(axis='columns', thresh=0.95) 
        
        return df

    def create_sheet(self,title):

        spreadsheet = {
            'properties': {
                'title': title
            }
        }
        spreadsheet = self.sheet.create(body=spreadsheet,
                                        fields='spreadsheetId').execute()

        sheetid = spreadsheet.get('spreadsheetId')
        print('Spreadsheet ID: {0}'.format(sheetid))
        #
        return sheetid

        
    def df_to_sheet(self,df,name):

        response = self.sheet.values().update(
            spreadsheetId=self.sheetid,
            valueInputOption='RAW',
            range=f'{name}!A1',
            body=dict(
                majorDimension='ROWS',
                values=df.T.reset_index().T.values.tolist())
        ).execute()
        
        return response


    
    def write_df(self,df,name):
        
        values = [df.columns.values.tolist()]
        values.extend(df.T.reset_index().T.values.tolist())  
        
        data = [{'range' : name, 'values' : df}]
        body = {
            'value_input_option': 'RAW',
            'data': values }

        response = (self.sheet.values()
                    .batchUpdate(spreadsheetId=self.sheetid, body=body)
                    .execute()
                   )
        return response
    
    def sheet_update(self,body, major='COLUMNS'): 
        '''
        if you want to update multiple ranges 
        Refer: https://developers.google.com/sheets/api/guides/values
        '''
        
        result = self.sheet.values().batchUpdate(spreadsheetId=self.sheetid, 
                                                 body=body).execute()

        print('{0} cells updated.'.format(result.get('totalUpdatedCells')))        
        
        return result

    def single_update(self,name, row_list, loc='A1', major='COLUMNS'):  
        '''
        if you want to update a single row 
        Refer: https://developers.google.com/sheets/api/guides/values
        
        row_list must be a list of lists: e,g [[cell_1],[cell_2],..]
        '''        

        try:
            if not isinstance(row_list[0],list):
                values = [[x] for x in row_list]
            else:
                values = row_list
        except:
            print('row_list must be a list of lists: e,g [[cell_1],[cell_2],..]')
            return
            
        body = {'values': values}
        
        #get data
        #Ref: https://developers.google.com/sheets/api/guides/values
        value_input_option = 'RAW'
        #drange = f'{name}!{start}{istart}:{end}{iend}'
        drange = f'{name}!{loc}'
        result = self.sheet.values().update(spreadsheetId=self.sheetid, 
                                            range=drange,
                                            valueInputOption=value_input_option,
                                            body=body).execute()

        print('{0} cells updated.'.format(result.get('updatedCells')))        
        
        return result  
       
if '__main__' == __name__:
    sid_radar = '15m7txkNxxMzHaONkS3kqpFJRMhGKUBaeWFGITfVmuLY'
    gd = gsheet(sheetid=sid_radar,fauth='gdrive_10acad_auth.json')
    dflist = {}
    for i in [1,2,3,4,6,7,8,9,11,12]:
        wname = f'Week{i}'
        
        try:
            df = gd.get_sheet_df(wname)
            dflist[wname] = df
            print(df.head())
            print(f'------------{wname} df.shape={df.shape}----')
            break
        except:
            print(f'ERROR: Could not obtain sheet for {wname}')