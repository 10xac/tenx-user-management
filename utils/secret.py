import sys, os
import time
import glob
import json
import subprocess
import requests
import tempfile
import base64
import logging
import threading
import boto3
from botocore.exceptions import ClientError
from typing import Optional, Dict, Any

region_name = "us-east-1"

# Cache configuration
ENVDIR = os.environ.get("ENVDIR", ".envdir")
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days in seconds

# In-memory cache: {secret_name: {"data": dict, "timestamp": float}}
_secrets_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()

logger = logging.getLogger(__name__)


# =============================================================================
# Cache Utility Functions
# =============================================================================

def get_secrets_cache_filename(sname: str) -> str:
    """
    Get the cache filename for a given secret name.
    Sanitizes the secret name for use as a filename.
    """
    sanitized = sname.replace("/", "_").replace("\\", "_")
    os.makedirs(ENVDIR, exist_ok=True)
    return os.path.join(ENVDIR, f"{sanitized}.json")


def safe_read_json(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Safely read JSON from a file. Returns None if file doesn't exist or is invalid.
    """
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read JSON from {filepath}: {e}")
    return None


def atomic_write_json(filepath: str, data: Dict[str, Any]) -> bool:
    """
    Atomically write JSON to a file using a temporary file and rename.
    Returns True on success, False on failure.
    """
    try:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        temp_path = filepath + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, filepath)
        return True
    except (IOError, OSError) as e:
        logger.error("Failed to write JSON to %s: %s", filepath, e)
        return False


def mask_secret_value(value: Any) -> str:
    """
    Mask a secret value for safe display.
    Shows **** followed by last 4 characters for strings > 4 chars.
    """
    if value is None:
        return "<None>"
    if isinstance(value, (dict, list)):
        return "<complex>"
    str_val = str(value)
    if len(str_val) <= 4:
        return "****"
    return f"****{str_val[-4:]}"


def is_cache_fresh(timestamp: float) -> bool:
    """
    Check if a cache entry is still fresh based on TTL.
    """
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def clear_secrets_cache(sname: str = "tenx/env/vars") -> Dict[str, Any]:
    """
    Clear both memory and file cache for a given secret name.
    Returns status dict with what was cleared.
    """
    result = {"memory_cleared": False, "file_cleared": False, "file_path": None}
    
    # Clear memory cache
    with _cache_lock:
        if sname in _secrets_cache:
            del _secrets_cache[sname]
            result["memory_cleared"] = True
    
    # Clear file cache
    cache_file = get_secrets_cache_filename(sname)
    result["file_path"] = cache_file
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            result["file_cleared"] = True
        except OSError as e:
            logger.error("Failed to remove cache file %s: %s", cache_file, e)
    
    logger.info(f"Cleared cache for {sname}: {result}")
    return result


def get_all_secrets(sname: str = "tenx/env/vars") -> Dict[str, Any]:
    """
    Get all secrets from cache (memory -> file -> AWS), updating caches as needed.
    
    Priority:
    1. Memory cache (if fresh)
    2. File cache (if fresh, also populates memory)
    3. AWS Secrets Manager (populates both caches)
    """
    # 1. Check memory cache
    with _cache_lock:
        if sname in _secrets_cache:
            entry = _secrets_cache[sname]
            if is_cache_fresh(entry["timestamp"]):
                logger.debug(f"Returning {sname} from memory cache")
                return entry["data"]
    
    # 2. Check file cache
    cache_file = get_secrets_cache_filename(sname)
    cached_data = safe_read_json(cache_file)
    if cached_data:
        file_mtime = os.path.getmtime(cache_file)
        if is_cache_fresh(file_mtime):
            logger.info(f"Loading {sname} from file cache: {cache_file}")
            with _cache_lock:
                _secrets_cache[sname] = {"data": cached_data, "timestamp": file_mtime}
            return cached_data
    
    # 3. Fetch from AWS
    logger.info(f"Fetching {sname} from AWS Secrets Manager")
    try:
        raw_secret = get_ssm_secret(sname)
        if isinstance(raw_secret, str):
            secrets_data = json.loads(raw_secret)
        else:
            secrets_data = raw_secret
        
        # Update both caches
        current_time = time.time()
        with _cache_lock:
            _secrets_cache[sname] = {"data": secrets_data, "timestamp": current_time}
        atomic_write_json(cache_file, secrets_data)
        
        return secrets_data
    except Exception as e:
        logger.error(f"Failed to fetch {sname} from AWS: {e}")
        raise


def force_refresh_secrets(sname: str = "tenx/env/vars") -> Dict[str, Any]:
    """
    Force refresh secrets by clearing cache and fetching fresh from AWS.

    Args:
        sname: secret name to refresh

    Returns the refreshed secrets dict.
    """
    # Clear existing cache
    clear_secrets_cache(sname)
    
    # Fetch fresh
    secrets = get_all_secrets(sname)
    
    logger.info(f"Refreshed {len(secrets)} secrets from {sname}")
    return secrets


def get_cache_metadata(sname: str = "tenx/env/vars") -> Dict[str, Any]:
    """
    Get metadata about the cache for a given secret name.
    """
    result = {
        "secret_name": sname,
        "memory_cache": {"exists": False, "age_seconds": None, "is_fresh": False, "key_count": 0},
        "file_cache": {"exists": False, "path": None, "age_seconds": None, "is_fresh": False, "key_count": 0}
    }
    
    # Check memory cache
    with _cache_lock:
        if sname in _secrets_cache:
            entry = _secrets_cache[sname]
            age = time.time() - entry["timestamp"]
            result["memory_cache"] = {
                "exists": True,
                "age_seconds": round(age, 2),
                "is_fresh": is_cache_fresh(entry["timestamp"]),
                "key_count": len(entry["data"]) if isinstance(entry["data"], dict) else 0
            }
    
    # Check file cache
    cache_file = get_secrets_cache_filename(sname)
    result["file_cache"]["path"] = cache_file
    if os.path.exists(cache_file):
        file_mtime = os.path.getmtime(cache_file)
        age = time.time() - file_mtime
        cached_data = safe_read_json(cache_file)
        result["file_cache"] = {
            "exists": True,
            "path": cache_file,
            "age_seconds": round(age, 2),
            "is_fresh": is_cache_fresh(file_mtime),
            "key_count": len(cached_data) if isinstance(cached_data, dict) else 0
        }
    
    result["ttl_seconds"] = CACHE_TTL_SECONDS
    return result


def clear_api_key_cache():
    """
    Clear the lru_cache for get_api_key in api.core.security.
    Call this after refreshing secrets to ensure API key changes take effect.
    """
    try:
        from api.core.security import get_api_key
        get_api_key.cache_clear()
        logger.info("Cleared get_api_key lru_cache")
        return True
    except Exception as e:
        logger.warning(f"Could not clear get_api_key cache: {e}")
        return False

def init_aws_session():
    # Create a Secrets Manager client
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    return client


def create_secret(secret_name, key, value):
    client = init_aws_session()

    # get original secrets
    res = client.update_secret(SecretId=secret_name, SecretString=json.dumps({key: value}))

    return res

def update_secret(secret_name, kv):
    client = init_aws_session()
    # get original secrets
    secret = get_secret(secret_name)
    secret.update(kv)
    res = client.update_secret(SecretId=secret_name, SecretString=json.dumps(secret))
    #print(secret)
    return res


def get_ssm_secret(secret_name):
    client = init_aws_session()

    # In this sample we only handle the specific exceptions for the 'GetSecretValue' API.
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    # We rethrow the exception by default.

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
        elif 'SecretBinary' in get_secret_value_response.keys():
            secret = base64.b64decode(get_secret_value_response['SecretBinary'])
        else:
            secret = get_secret_value_response


    return secret


def config_from_string(sdata,fname=None,rfile=False):
    '''
    sdata: string data
    fname: file name to save
    rfile: return file object
    '''

    if isinstance(sdata, str):
        data = json.loads(sdata)
    else:
        data = sdata

    try:
        if fname:
            #make dir  
            if not os.path.dirname(fname):
                fname = lambda_friendly_path(fname)
        
            os.makedirs(os.path.dirname(fname),exist_ok=True)

            print(f'writing {fname} file ..')
            #dump it to json file       
            with open(fname, 'w') as f:
                json.dump(data, f)

            if rfile:
                return fname
            else:
                return data
    except:
        print(f'------warning: saving {fname} failed----')
        return None
        


def get_secret(pname, pvar=None,fname=''):
    
    authData = None
    if pvar is not None:
        if pvar in os.environ.keys():
            sdata = os.environ.get(pvar)
            authData = json.loads(sdata)
            return authData
    
    
    authData = config_from_string(get_ssm_secret(pname), fname=fname)
    #    
    return authData
    
def get_secret_env(pname, pvar=None,fname=''):
    
    authData = None
    if pvar is not None:
        if pvar in os.environ.keys():
            sdata = os.environ.get(pvar)
            authData = json.loads(sdata)
            return authData
    
    
    authData = json.loads(get_ssm_secret(pname))
    #    
    return authData    

def is_lambda():
    c1 = os.environ.get("LAMBDA_TASK_ROOT") is not None
    c2 = os.environ.get("AWS_EXECUTION_ENV") is not None
    c3 = os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None

    return c1 or c2 or c3

def lambda_friendly_path(fpath):
    basename = os.path.basename(fpath)
    dirname = tempfile.gettempdir()
    if is_lambda():
        f = f'/tmp/{basename}'
    else:
        os.makedirs(dirname, exist_ok=True)
        f = f"{dirname}/{basename}"
    return f


def get_auth(ssmkey=None, envvar=None, fconfig=None, rfile=False, write_to_path=None):
    """
    Wrapper to get auth from env, .envdir cache, or SSM.

    Order:
    1) envvar override (if provided and set)
    2) tenx/env/vars from .envdir cache (via get_all_secrets), then lookup ssmkey within it
    3) direct SSM fetch for ssmkey
    """
    caller_line_number = sys._getframe(1).f_lineno
    caller_filename = sys._getframe(1).f_code.co_filename
    caller_filename = caller_filename.split('/')[-1] if '/' in caller_filename else caller_filename
    caller_func_name = sys._getframe(1).f_code.co_name
    print(f'{caller_filename}:{caller_func_name}:{caller_line_number}: get_auth(ssmkey={ssmkey}, envvar={envvar})')

    # 1) Environment variable override
    if envvar:
        val = os.environ.get(envvar, '')
        if val not in ['', 'null', 'None']:
            try:
                return config_from_string(val)
            except Exception:
                print(f'getting env variable {envvar} failed!')

    # 2) Try from tenx/env/vars cache in .envdir
    try:
        secrets_bundle = get_all_secrets("tenx/env/vars")
        if ssmkey:
            # direct hit in bundle
            if ssmkey in secrets_bundle:
                return secrets_bundle[ssmkey]
            # mapping support
            keys_map = {
                'strapi/alml-cms/token': 'ALML_STRAPI_TOKEN',
                'staging/strapi/token': 'TENX_STAGING_STRAPI_TOKEN',
                'dev/strapi/token': 'TENX_DEV_STRAPI_TOKEN',
                'prod/strapi/token': 'TENX_PROD_STRAPI_TOKEN',
                'git_token_tenx': 'GIT_TOKEN_10ACADEMY',
                'tenx/db/strapi': {
                    'STRAPI_PGDB_USERNAME': 'username',
                    'STRAPI_PGDB_PASSWORD': 'password',
                    'STRAPI_PGDB_ENGINE': 'engine',
                    'STRAPI_PGDB_HOST': 'host',
                    'STRAPI_PGDB_PORT': 'port',
                    'STRAPI_PGDB_IDENTIFIER': 'dbInstanceIdentifier'
                },
                'strapi/prod/email': [
                    'AWS_SES_KEY',
                    'AWS_SES_SECRET'
                ]
            }
            if ssmkey in keys_map:
                res = keys_map[ssmkey]
                if isinstance(res, dict):
                    auth = {}
                    for kold, knew in res.items():
                        auth[knew] = secrets_bundle[kold]
                    return auth
                if isinstance(res, list):
                    auth = {}
                    for k in res:
                        auth[k] = secrets_bundle[k]
                    return auth
                return secrets_bundle[res]
    except Exception:
        logger.error("Failed to fetch secrets from tenx/env/vars cache. Defaulting to SSM.")
        pass

    # 3) Fallback: direct SSM for ssmkey
    if ssmkey:
        try:
            auth = get_secret(ssmkey)
            # Optionally write to file for consumers that expect a path (e.g., gdrive)
            target_path = write_to_path or fconfig
            if target_path and isinstance(auth, (dict, list, str)):
                try:
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(os.path.expanduser(target_path)) or ".", exist_ok=True)
                    with open(os.path.expanduser(target_path), "w") as f:
                        json.dump(auth, f, indent=2) if isinstance(auth, (dict, list)) else f.write(str(auth))
                except Exception as e:
                    logger.error(f'writing auth to {target_path} failed: {e}')
            return auth
        except Exception:
            logger.error(f'getting secret {ssmkey} from aws ssm failed!')
            raise

    raise ValueError(f'Credential cannot be obtained. ssmkey={ssmkey}, envvar={envvar}')

def get_google_service_account(ssmkey="gspread/config",
                                envvar="gclass_credentials.json",
                                fconfig=".env/gclass_credentials.json",
                                rfile=True):
    
    caller_line_number = sys._getframe(1).f_lineno        
    caller_filename = sys._getframe(1).f_code.co_filename
    caller_filename = caller_filename.split('/')[-1] if '/' in caller_filename else caller_filename      
    caller_func_name = sys._getframe(1).f_code.co_name    
    print(f'{caller_filename}:{caller_func_name}:{caller_line_number} Getting google service account ..')

    return get_auth(ssmkey=ssmkey,
                    envvar=envvar,
                    fconfig=fconfig, 
                    rfile=rfile)                    
  
    

if __name__ == "__main__":
    
    path = os.path.dirname(os.path.realpath(__file__))
    path = os.path.dirname(path)

    print(f"Testing secret retrieval from {path}")
    print(f"Cache directory: {ENVDIR}")
    
    # Test get_all_secrets (uses .envdir cache)
    secrets = get_all_secrets("tenx/env/vars")
    print(f"Retrieved {len(secrets)} secrets")
    
    # Test get_auth
    _ = get_auth(ssmkey="tenx/env/vars", envvar='all_tenx_env_vars')
    print(f"get_auth returned {len(_) if isinstance(_, dict) else 'non-dict'} items")
