
import urllib.request

url = "http://localhost:5173/"
try:
    with urllib.request.urlopen(url) as response:
        print(f"Status Code: {response.getcode()}")
        # print(f"Response Body: {response.read().decode('utf-8')[:100]}")
except Exception as e:
    print(f"Error: {e}")
