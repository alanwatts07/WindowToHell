import asyncio
import websockets
import json
import requests
from PIL import Image, ImageTk
import tkinter as tk
from io import BytesIO
import time
import queue
import threading
import signal

# Global variables
shutdown_requested = False
image_queue = queue.Queue(maxsize=5)  # Limit the queue size to prevent overflow


# Function to fetch metadata and image from the metadata URI
async def fetch_metadata_and_image(metadata_uri):
    try:
        # Fetch the metadata JSON from the provided URI
        response = requests.get(metadata_uri, timeout=5)  # Timeout to avoid hanging
        response.raise_for_status()

        # Parse the metadata JSON
        metadata = response.json()
        print(f"Metadata: {metadata}")

        # Check if the metadata contains an image field
        if "image" in metadata:
            image_uri = metadata["image"]

            # Replace IPFS link with HTTP gateway if needed
            if image_uri.startswith("ipfs://"):
                image_uri = image_uri.replace("ipfs://", "https://ipfs.io/ipfs/")

            print(f"Fetching image from: {image_uri}")

            # Fetch and return the image
            return fetch_image(image_uri)

    except requests.RequestException as e:
        print(f"Failed to fetch metadata: {e}")
    except Exception as e:
        print(f"Error processing metadata or image: {e}")


# Function to fetch an image from a URI
def fetch_image(image_uri):
    try:
        # Fetch the image data
        response = requests.get(image_uri, timeout=5)  # Timeout to avoid hanging
        response.raise_for_status()

        # Load the image into a PIL Image object
        image = Image.open(BytesIO(response.content))

        # Resize the image
        return image.resize((400, 400))

    except requests.RequestException as e:
        print(f"Failed to fetch image: {e}")
    except Exception as e:
        print(f"Error loading image: {e}")


# WebSocket subscription with reconnection logic
async def subscribe():
    global shutdown_requested
    uri = "wss://pumpportal.fun/api/data"
    retry_delay = 1  # Initial retry delay in seconds

    while not shutdown_requested:
        try:
            async with websockets.connect(uri) as websocket:
                # Subscribe to new token events
                payload = {"method": "subscribeNewToken"}
                await websocket.send(json.dumps(payload))
                print("Subscribed to NewToken events.")

                while not shutdown_requested:
                    message = await websocket.recv()
                    data = json.loads(message)

                    # Check if the message contains a metadata URI
                    if "uri" in data:
                        metadata_uri = data["uri"]
                        print(f"Metadata URI found: {metadata_uri}")

                        # Fetch the image and put it in the queue
                        image = await fetch_metadata_and_image(metadata_uri)
                        if image:
                            if not image_queue.full():
                                image_queue.put(image)
                            else:
                                print("Queue full. Dropping oldest image.")

                retry_delay = 1  # Reset retry delay on successful connection

        except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK):
            print("WebSocket connection closed. Reconnecting...")
        except Exception as e:
            print(f"WebSocket error: {e}")

        if not shutdown_requested:
            print(f"Reconnecting in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)  # Exponential backoff


# Signal handler for graceful shutdown
def handle_shutdown_signal(signal_num, frame):
    global shutdown_requested
    print("\nCtrl+C detected. Preparing to shutdown...")
    shutdown_requested = True


# GUI setup
class ImageDisplayApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Viewer")
        self.label = tk.Label(root, text="Waiting for images...", font=("Helvetica", 16))
        self.label.pack(pady=10)

        # Placeholder for the image display
        self.image_label = tk.Label(root)
        self.image_label.pack()

        # Last update time
        self.last_update_time = 0

        # Start a periodic update task
        self.update_task()

    def update_task(self):
        # Check if there's a new image in the queue
        if not image_queue.empty() and time.time() - self.last_update_time >= 2:
            self.last_update_time = time.time()
            image = image_queue.get()

            # Convert PIL Image to a format Tkinter can use
            tk_image = ImageTk.PhotoImage(image)
            self.image_label.config(image=tk_image)
            self.image_label.image = tk_image  # Keep a reference to avoid garbage collection

        # Schedule the next update
        self.root.after(100, self.update_task)


# Run the application
def main():
    global shutdown_requested

    # Register signal handler
    signal.signal(signal.SIGINT, handle_shutdown_signal)

    root = tk.Tk()
    app = ImageDisplayApp(root)

    # Run the WebSocket listener in an asyncio event loop
    def start_asyncio_loop():
        asyncio.run(subscribe())

    # Start the asyncio loop in a separate thread
    loop_thread = threading.Thread(target=start_asyncio_loop, daemon=True)
    loop_thread.start()

    # Start the Tkinter event loop
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Exiting...")

    # Wait for WebSocket to close gracefully
    shutdown_requested = True
    loop_thread.join()


if __name__ == "__main__":
    main()
