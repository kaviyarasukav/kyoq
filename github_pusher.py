import urllib.request
import urllib.parse
import urllib.error
import json
import time
import os
import base64

CLIENT_ID = "01ab8ac9400c4e429b23" # GitHub VS Code Client ID

def make_request(url, data=None, headers=None, method="POST"):
    if headers is None:
        headers = {'Accept': 'application/json'}
    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        data = urllib.parse.urlencode(data).encode('utf-8')
    try:
        with urllib.request.urlopen(req, data=data) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            return json.loads(body)
        except Exception:
            return {"error": str(e), "body": body}

def get_device_code():
    url = "https://github.com/login/device/code"
    data = {"client_id": CLIENT_ID, "scope": "repo"}
    return make_request(url, data)

def poll_for_token(device_code, interval):
    url = "https://github.com/login/oauth/access_token"
    data = {
        "client_id": CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }
    while True:
        res = make_request(url, data)
        if "access_token" in res:
            return res["access_token"]
        elif res.get("error") == "authorization_pending":
            time.sleep(interval)
        else:
            print("Error polling token:", res)
            return None

def api_call(endpoint, token, method="GET", json_data=None):
    url = f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    data = None
    if json_data is not None:
        data = json.dumps(json_data).encode('utf-8')
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            return json.loads(body)
        except:
            return {"error": str(e), "body": body}

def push_repo(token):
    # Get Username
    user_info = api_call("/user", token)
    username = user_info.get("login")
    if not username:
        print("Failed to get username")
        return
    print(f"\nLogged in as {username}!")

    # Create Repo
    repo_name = "kyoq"
    print(f"Creating repository '{repo_name}'...")
    repo_res = api_call("/user/repos", token, method="POST", json_data={"name": repo_name, "private": False, "description": "Delta Exchange Auto-Pilot Monitor"})
    if "name" not in repo_res and "errors" not in repo_res:
        if repo_res.get("message") != "name already exists on this account":
            print("Error creating repo:", repo_res)
            return
            
    print("Repository created or already exists. Uploading files...")
    
    # Upload all relevant files in the directory, strictly excluding private credentials
    files_to_upload = [f for f in os.listdir('.') if os.path.isfile(f) and not f.endswith(('.log', '.pid', '.zip', '.pyc', '.pyd')) and not f.startswith('__') and not f.startswith('.env')]
    
    for file_name in files_to_upload:
        if not os.path.exists(file_name):
            continue
            
        with open(file_name, "rb") as f:
            content = f.read()
            
        b64_content = base64.b64encode(content).decode('utf-8')
        
        # Check if file already exists to get its SHA
        file_info = api_call(f"/repos/{username}/{repo_name}/contents/{file_name}", token)
        sha = file_info.get("sha") if "sha" in file_info else None
        
        payload = {
            "message": f"Upload {file_name}",
            "content": b64_content
        }
        if sha:
            payload["sha"] = sha
            
        print(f"Uploading {file_name}...")
        res = api_call(f"/repos/{username}/{repo_name}/contents/{file_name}", token, method="PUT", json_data=payload)
        if "content" in res:
            print(f" -> Success!")
        else:
            print(f" -> Error: {res}")
            
    print(f"\nAll done! Your code is live at: https://github.com/{username}/{repo_name}")

if __name__ == "__main__":
    print("Initializing GitHub Device Login Flow...")
    auth_data = get_device_code()
    if "user_code" in auth_data:
        print("\n" + "="*50)
        print("1. Open your browser to:", auth_data['verification_uri'])
        print("2. Enter the following code:", auth_data['user_code'])
        print("="*50 + "\n")
        print("Waiting for authorization... (do not close this window)")
        
        token = poll_for_token(auth_data['device_code'], auth_data['interval'])
        if token:
            print("Authorization successful!")
            push_repo(token)
    else:
        print("Failed to start device flow:", auth_data)
