import os

import requests
import hashlib
from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from config import default_log, KITE_API_URL, zerodha_api_key, zerodha_api_secret, KITE_API_LOGIN_URL, homepage_url
from decorators.handle_generic_exception import frontend_api_generic_exception
from external_services.zerodha.zerodha_orders import store_access_token_of_kiteconnect, \
    get_access_token_from_request_token
from logic.zerodha_integration_management.zerodha_integration_logic import get_zerodha_equity
from standard_responses.standard_json_response import standard_json_response

kite_connect_router = APIRouter(prefix='/kite-connect', tags=['kite-connect'])


@kite_connect_router.get('/current-equity')
@frontend_api_generic_exception
def get_current_kite_equity(request: Request):
    default_log.debug(f"inside /current-equity")

    current_equity = get_zerodha_equity()

    default_log.debug(f"Current Equity returned: {current_equity}")

    return standard_json_response(
        error=False,
        message="ok",
        data={
            'current_equity': current_equity
        }
    )


@kite_connect_router.get('/access-token-status')
@frontend_api_generic_exception
def get_access_token_status(request: Request):
    default_log.debug(f"inside /kite-connect/access-token-status")

    access_token_file_path = 'access_token.txt'
    access_token_set_status = False
    try:
        if os.path.exists(access_token_file_path):
            default_log.debug(f"Since {access_token_file_path} exists so setting access_token_set_status as True")
            access_token_set_status = True

    except Exception as e:
        default_log.debug(f"An error occurred while checking access token path exists or not. Error={e}")
        return standard_json_response(
            error=True,
            message="An error occurred while checking access token has been set or not",
            data={}
        )

    default_log.debug(f"Current status of access token = {access_token_set_status}")
    return standard_json_response(
        error=False,
        message="ok",
        data={
            'access_token_set_status': access_token_set_status
        }
    )


@kite_connect_router.get("/login")
@frontend_api_generic_exception
def add_symbol_budget_route(request: Request):
    default_log.debug("inside /kite-connect/login api route")

    authorize_url = f"{KITE_API_LOGIN_URL}/connect/login?v=3&api_key={zerodha_api_key}"
    return RedirectResponse(authorize_url)
    # other_url = "http://localhost:5000/kite-connect/callback?request_token=8b178g4hg4jh8674kjk1j&state=true"
    # response = requests.get(other_url)
    # token_data = response.json()
    # return RedirectResponse(other_url)


@kite_connect_router.post("/get-access-token")
@frontend_api_generic_exception
def get_kiteconnect_access_token_route(
        request: Request,
        request_token: str
):
    default_log.debug(f"inside /get-access-token with request_token={request_token}")

    access_token = get_access_token_from_request_token(request_token)

    if access_token is None:
        default_log.debug(f"An error occurred while getting access token from request_token={request_token}")
        return standard_json_response(
            error=True,
            message="An error occurred while getting access token from request_token",
            data={}
        )

    default_log.debug(f"Access token received for request_token={request_token} is {access_token}")
    return standard_json_response(
        error=False,
        message="ok",
        data={
            'access_token': access_token
        }
    )


# This route handles the callback from Kite
@kite_connect_router.get("/callback")
async def callback(request: Request, request_token: str):
    default_log.debug(f"inside /kite-connect/callback with request_token={request_token}")
    # Calculate the checksum
    checksum_data = zerodha_api_key + request_token + zerodha_api_secret
    checksum = hashlib.sha256(checksum_data.encode()).hexdigest()

    data = {
        'api_key': zerodha_api_key,
        'request_token': request_token,
        'checksum': checksum
    }

    token_url = f'{KITE_API_URL}/session/token'

    response = requests.post(token_url, data=data)
    token_data = response.json()

    # Check if the request was successful
    if response.status_code == 200 and token_data.get('status') == 'success':
        access_token = token_data['data']['access_token']
        default_log.debug(f"Access Token: {access_token}")
        store_access_token_of_kiteconnect(access_token)
        default_log.debug(f"Authorization successful")
        return RedirectResponse(homepage_url)
        # return standard_json_response(error=False, message="Authorization successful", data={})
    else:
        default_log.debug(f"Token exchange failed: {token_data}")
        return RedirectResponse(homepage_url)
        # return standard_json_response(error=False, message="Token exchange failed", data={})
