import threading
from pathlib import Path
import schedule
import time

import uvicorn
from fastapi.applications import FastAPI, RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles

from api.test.healthcheck import router as test_router

from fastapi.responses import HTMLResponse
import config
from api.user_management.user_auth import auth_router
from api.user_management.user_basic_api import user_router
from api.event_management.event_managment_crud_api import event_router

from external_services.global_datafeed.get_data import start_global_data_feed_server
from external_services.zerodha.zerodha_orders import check_open_position_status_and_close, get_indices_data, \
    get_access_token
from logic.zerodha_integration_management.zerodha_integration_logic import restart_event_threads, \
    store_all_symbol_budget, store_all_timeframe_budget
from standard_responses.standard_json_response import standard_json_response
from api.symbol_budget_route_management.symbol_budget_crud_api import symbol_budget_router
from api.kite_connect_route_management.kite_connect_api_routes import kite_connect_router

app = FastAPI()
origins = [
    "http://localhost",
    "http://localhost:4200",
    "http://localhost:3000"  # React
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test_router)
app.include_router(user_router)
app.include_router(auth_router)
app.include_router(kite_connect_router)
app.include_router(event_router)
app.include_router(symbol_budget_router)

app.mount("/assets/static",
          StaticFiles(directory=Path(config.dir_path) / 'static'), name="static")


@app.exception_handler(RequestValidationError)
async def default_exception_handler(request: Request, exc: RequestValidationError):
    return standard_json_response(
        status_code=200,
        data={},
        error=True,
        message=str(exc)
    )


@app.get('/')
def get_app_angular(path=None):
    with open('static/templates/index.html', 'r') as file_index:
        html_content = file_index.read()
    return HTMLResponse(html_content, status_code=200)


@app.get('/{path}')
def get_static_file_angular(path):
    try:
        with open(f'static/templates/{path}') as file_index:
            html_content = file_index.read()
    except Exception as ex:
        return RedirectResponse('/')
    media_type = 'text/html'
    if 'js' in path:
        media_type = 'text/javascript'
    if 'css' in path:
        media_type = 'text/css'
    return Response(html_content, status_code=200, media_type=media_type)


def run_scheduled_task():
    # Schedule the function to run at 3:20 PM IST
    schedule.every().day.at("15:20").do(check_open_position_status_and_close)

    # Keep the scheduled task running in a separate thread
    while True:
        schedule.run_pending()
        time.sleep(1)


@app.on_event("startup")
async def startup():
    # Start threads here
    # results = await asyncio.gather(Foo.get_instance())
    # app.state.ws = results[0][0]
    # asyncio.create_task(expire_time_check())
    get_access_token()
    get_indices_data()
    # start_kite_ticker()
    # Create a thread for the start_truedata_server function
    # Create a separate thread for the scheduled task
    scheduled_task_thread = threading.Thread(target=run_scheduled_task)

    # Start the thread
    scheduled_task_thread.start()

    # Load all symbol budgets
    store_all_symbol_budget()

    # Load all timeframe budgets and trade details
    store_all_timeframe_budget()

    # GLOBAL FEED DATA SERVER
    global_feed_data_thread = threading.Thread(target=start_global_data_feed_server)
    # Start the thread
    global_feed_data_thread.start()

    # Wait 5 seconds till GLOBAL data feed is not authenticated
    time.sleep(5)
    restart_event_threads()
    # pass


def create_app():
    return app


if __name__ == '__main__':
    app = create_app()
    uvicorn.run('main:app',
                host=config.fastapi_host, port=config.fastapi_port,
                reload=config.reload)
