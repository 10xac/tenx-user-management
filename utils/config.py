import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
#
import os, sys
import importlib.util
import uuid
from pathlib import Path
import hashlib
from dataclasses import dataclass

#
from contextlib import contextmanager

#
from utils.secret import get_auth





def get_openapi_token(
    ssmkey="OPENAI_API_KEY",
    envvar="openai_apikey",
    fconfig=".env/openai_apikey.json",
):
    apikey = get_auth(ssmkey=ssmkey, envvar=envvar, fconfig=fconfig)

    return apikey


def random_id():
    '''
    Generate a random id
    '''

    return uuid.uuid4().hex

def shash(s):
    '''
    Generate a hash value from a string

    Args:
        s (str): string to hash        
    '''

    # Getting the hash value using the hashlib library
    hash_value = hashlib.md5(s.encode()).hexdigest()
    return hash_value




@dataclass
class openai:
    max_calls = 3  # max number of maximum calls per tool function call
    temperature = float(os.environ.get('OPENAI_TEMPERATURE',0.8))
    top_p = float(os.environ.get('OPENAI_TOP_P',1.0))
    top_k = int(os.environ.get('OPENAI_TOP_K',0))
    #https://platform.openai.com/docs/models/continuous-model-upgrades
    #MAX_INPUT =128k tokens, MAX_OUTPUT = 4096 tokens
    max_tokens = int(os.environ.get('OPENAI_MAX_TOKENS',128000))
    max_chars = int(os.environ.get('OPENAI_MAX_CHARACTERS',32768))
    stop = os.environ.get('OPENAI_STOP','\n')
    model = os.environ.get('OPENAI_MODEL',"gpt-4-0125-preview")
    vision_model = os.environ.get('OPENAI_VISION_MODEL',"gpt-4-vision-preview")
    api_key = get_openapi_token()

strapi_stage =  os.environ.get('STRAPI_STAGE','unknown')
print(f'using STRAPI_STAGE={strapi_stage}')

def get_strapi_params(stage):
    if stage.lower().startswith('devapply'):
        root='dev-apply-cms'
        ssmkey="APPLY_DEV_STRAPI_TOKEN"
    elif stage.lower().startswith('apply'):
        root='apply-cms'
        ssmkey="APPLY_PROD_STRAPI_TOKEN" 
    elif stage.lower().startswith('devu2j'):#https://dev-u2jcms.10academy.org/graphql
        root='dev-u2jcms'#'dev-u2j-cms'
        ssmkey="U2J_DEV_STRAPI_TOKEN" 
    elif stage.lower().startswith('u2j'):
        root='u2jcms'
        ssmkey="U2J_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('kaim'):
        root='kaimcms'
        ssmkey="KAIM_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('kepler'):
        root='keplercms'
        ssmkey="KEPLER_PROD_STRAPI_TOKEN" 

    elif stage.lower().startswith('prod'):
        root='cms'
        ssmkey="TENX_PROD_STRAPI_TOKEN" 
    elif stage.lower().startswith('shared'):
        root='sharedcms'
        ssmkey="SHARED_PROD_STRAPI_TOKEN"
    else:  #stage.lower().startswith('dev')
        root='dev-cms'
        ssmkey="TENX_DEV_STRAPI_TOKEN"  

    return root, ssmkey   
    
root, ssmkey = get_strapi_params(strapi_stage)

@dataclass
class strapi:
    root = root
    ssmkey = ssmkey
    stage = strapi_stage

#
cdir = os.path.dirname(os.path.realpath(__file__))
efs_path = '/mnt/efs/autograde'
stage = os.environ.get('STAGE', 'dev')
inaws = os.path.exists(efs_path)

#
apipath = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) #./api
rootdir = os.path.dirname(apipath)


if os.path.exists(efs_path):
   print(f'**** using {efs_path} as root location to .env, conf, static/ and templates/ folders!')


if os.path.exists(efs_path):
    model_path = f'{efs_path}/{stage}/'
else:
    model_path = f'{apipath}'


@dataclass
class folders:
    rootdir = rootdir
    if os.path.exists(f'{efs_path}/.env'):
        envdir = f"{efs_path}/.env"
    else:
        envdir = f"{rootdir}/.env"

    if os.path.exists(f'{efs_path}/conf'):
        kedroconfdir = f"{efs_path}/conf"
    else:
        kedroconfdir = f"{rootdir}/conf"
        
    #
    if os.path.exists(efs_path):
        templates: str = f'{efs_path}/templates'
        static: str = f'{efs_path}/static'
        test_data: str = f'{efs_path}/test_data'        
    else:
        templates: str = f'{apipath}/templates'
        static: str = f'{apipath}/static'
        test_data: str = f'{apipath}/test_data'        



@dataclass
class settings:
    PROJECT_NAME: str = "10 Academy Tenx Data Loader"
    PROJECT_DESCRIPTION = "Tenx Data Loader"
    PROJECT_VERSION: str = "1.0.1"
    #
    USE_SQLITE_DB: str = "False"
    #
    SECRET_KEY: str = os.getenv("SECRET_KEY","")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30  # in mins
    AUTHENTICATED_USER = False
    #
    TEST_USER_EMAIL = "test@example.com"
    



@dataclass
class PGDB:    
    POSTGRES_USER: str = os.getenv("POSTGRES_USER","")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD","")
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "localhost")
    POSTGRES_PORT: str = os.getenv(
        "POSTGRES_PORT", 5432
    )  # default postgres port is 5432
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "tdd")
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_SERVER}:{POSTGRES_PORT}/{POSTGRES_DB}"



      
    



    








