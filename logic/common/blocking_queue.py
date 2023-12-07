import time

from config import default_log
import queue
import threading

from external_services.zerodha.zerodha_orders import get_kite_account_api


class BlockingQueue:
    def __init__(self, max_size):
        self.queue = queue.Queue(max_size)
        self.lock = threading.Lock()
        self.status_dictionary = {}
        self.kite = get_kite_account_api()

        # Start a background thread to run find_order_status every 15 seconds
        self.background_thread = threading.Thread(target=self.run_find_order_status, daemon=True)
        self.background_thread.start()

    def put(self, item):
        with self.lock:
            self.queue.put(item)
            self._update_status(item)

    def get(self):
        with self.lock:
            return self.queue.get()

    def _update_status(self, item):
        order_details = self.kite.order_history(item)
        status = order_details[-1]["status"]
        default_log.debug(f"Updating status of order_id={item} to {status}")
        self.status_dictionary[item] = status

    def find_order_status(self):
        with self.lock:
            default_log.debug(f"inside find_order_status with queue={self.queue}")
            default_log.debug(f"Status Dictionary={self.status_dictionary}")

            while not self.queue.empty():
                if self.queue.empty():
                    break  # Exit the loop if the queue is empty

                order_id = self.queue.get()

                # Check if the queue is empty after getting an item
                if self.queue.empty():
                    break  # Exit the loop if the queue is empty

                self._update_status(order_id)

                if self.status_dictionary[order_id] == "COMPLETE":
                    default_log.debug(f"Order with id={order_id} status is COMPLETE")
                else:
                    default_log.debug(f"Order with id={order_id} status is {self.status_dictionary[order_id]}")
                    # Put the order_id back into the queue if it's not completed
                    self.queue.put(order_id)

    def run_find_order_status(self):
        while True:
            time.sleep(15)
            with self.lock:
                if not self.queue.empty():
                    default_log.debug(f"Running find_order_status in the background with queue={self.queue}")
                    self.find_order_status()


# Singleton pattern to ensure a single instance of the queue across the project
_blocking_queue_instance = None


def get_blocking_queue():
    global _blocking_queue_instance
    if _blocking_queue_instance is None:
        _blocking_queue_instance = BlockingQueue(max_size=10)  # Adjust the size as needed
    return _blocking_queue_instance
