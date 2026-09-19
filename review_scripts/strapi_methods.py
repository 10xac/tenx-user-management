
from numpy import int64
import pandas as pd
import requests
import json
import time
import os,sys
import numpy as np

# from pathfig import *
import os, sys
curdir = os.path.dirname(os.path.realpath(__file__))
cpath = os.path.dirname(curdir)
print(cpath)
if not cpath in sys.path:
    sys.path.append(cpath)
from utils.secret import get_auth, lambda_friendly_path
from api.core.config import get_strapi_params, strapi_stage



class StrapiMethods:
    def __init__(self, **kwargs):

        run_stage =  kwargs.get('run_stage',strapi_stage)
        
        print('Strapimethods run_stage:', run_stage)
        root, ssmkey = get_strapi_params(run_stage)
        
        if run_stage.lower().startswith('tenacious'):
            self.apiroot = f"https://cms.gettenacious.com" 
        else:
            self.apiroot = f"https://{root}.10academy.org"



        self.ssmkey = ssmkey
        
        self.token = get_auth(ssmkey,  envvar='STRAPI_TOKEN', fconfig=lambda_friendly_path(f'.env/{root}.json'))

        self.headers = {"Authorization": f"Bearer {self.token}"}


    def fetch_data(self,table, token):
        r = requests.get(table,headers = {

                        "Authorization": f"Bearer {token}", 

                        "Content-Type": "application/json"})
        return r.json()
    
                
    def update(self,table, id, params, token):
        
        r = requests.put(table+ str(id),
        data=json.dumps({
           "data":params
        }),
        headers={
            "Authorization": f"Bearer {token}", 
            'Content-Type': 'application/json'
        })
        
        
    # Retried because the failure is transient and the caller cannot tell.
    #
    # A 30-row batch makes ~150 of these calls in about a minute. On 2026-09-19
    # batch 69 lost 17 of 30 rows to this: Strapi refused a share of the writes
    # under that rate, and every one of them was reported to the admin as a
    # permanent failure. Replaying the same 17 afterwards with a 1.5s gap
    # between them succeeded 17 out of 17, with no other change - which is what
    # proved the failure was throughput and not the data.
    _RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
    _MAX_ATTEMPTS = 4

    def insert_data(self, data, table):
        url = self.apiroot + "/api/" + table
        print(url)
        last_error = None

        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url,
                    data=json.dumps({"data": data}),
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    # Without a timeout a hung write blocks the whole batch on
                    # one row, for as long as the socket stays open.
                    timeout=30,
                )
            except Exception as exc:
                # The original `except` printed and then `return r` with r never
                # assigned, so a network error raised UnboundLocalError from
                # inside the error handler and buried the real cause.
                last_error = f"{type(exc).__name__}: {exc}"
                response = None

            if response is not None:
                if response.status_code not in self._RETRY_STATUSES:
                    try:
                        return response.json()
                    except ValueError:
                        return {
                            "error": {
                                "status": response.status_code,
                                "message": f"Non-JSON response from {table}",
                                "body": response.text[:500],
                            }
                        }
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"

            if attempt < self._MAX_ATTEMPTS:
                # Exponential, so a rate limit gets a widening gap rather than
                # three more requests into the same closed door.
                time.sleep(0.75 * (2 ** (attempt - 1)))

        # Structured, so the caller can say what went wrong instead of guessing.
        return {
            "error": {
                "status": 0,
                "message": f"{table}: giving up after {self._MAX_ATTEMPTS} attempts - {last_error}",
                "error_message": f"{table} write failed after {self._MAX_ATTEMPTS} attempts: {last_error}",
                "transient": True,
            }
        }
    
  