from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import requests
import base64
from datetime import datetime
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# Explicitly load .env from the current directory
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# Debug: Check if variables are loaded
print("🔍 Checking environment variables:")
print(f"CONSUMER_KEY: {os.getenv('CONSUMER_KEY')}")
print(f"CONSUMER_SECRET: {os.getenv('CONSUMER_SECRET')}")
print(f"SHORTCODE: {os.getenv('SHORTCODE')}")
print(f"PASSKEY: {os.getenv('PASSKEY')[:20]}..." if os.getenv('PASSKEY') else "NOT FOUND")
print(f"CALLBACK_URL: {os.getenv('CALLBACK_URL')}")

app = Flask(__name__)
CORS(app)

# In-memory users
users = {}

@app.route('/')
def home():
    return "Binary Cash Backend is Running!"

@app.route('/api/test')
def test():
    return jsonify({"message": "Backend connected!", "status": "ok"})

# ====================== REGISTER ======================
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    phone = data.get('phone')
    password = data.get('password')

    if not all([username, email, phone, password]):
        return jsonify({"error": "All fields required"}), 400

    if username in users:
        return jsonify({"error": "Username already exists"}), 400

    users[username] = {
        "email": email,
        "phone": phone,
        "password": password,
        "balance": 5000.0
    }

    return jsonify({"success": True, "message": "Account created!", "user": {"username": username, "balance": 5000.0}})

# ====================== LOGIN ======================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user = users.get(username)
    if not user or user['password'] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({
        "success": True,
        "user": {"username": username, "balance": user['balance']}
    })

# ====================== GET ACCESS TOKEN ======================
def get_access_token():
    """Get OAuth access token from M-Pesa"""
    try:
        consumer_key = os.getenv('CONSUMER_KEY')
        consumer_secret = os.getenv('CONSUMER_SECRET')
        
        if not consumer_key or not consumer_secret:
            print("❌ Missing Consumer Key or Secret!")
            return None
            
        # Use sandbox URL (since we're testing)
        base_url = "https://sandbox.safaricom.co.ke"
        url = f"{base_url}/oauth/v1/generate?grant_type=client_credentials"
        
        print("🔄 Getting access token...")
        response = requests.get(
            url,
            auth=HTTPBasicAuth(consumer_key, consumer_secret),
            timeout=10
        )
        
        print(f"✅ Token response status: {response.status_code}")
        
        if response.status_code == 200:
            token = response.json()['access_token']
            print(f"✅ Got token: {token[:20]}...")
            return token
        else:
            print(f"❌ Token error: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Token error: {str(e)}")
        return None

# ====================== M-PESA STK PUSH ======================
@app.route('/api/payments/stk-push', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        phone = data.get('phone')
        username = data.get('username', 'guest')

        print(f"[STK] Request - Amount: {amount}, Phone: {phone}")

        if amount < 250 or not phone:
            print("[STK] Error: Missing data")
            return jsonify({"error": "Amount and phone required"}), 400

        # Format phone number
        phone = phone.strip().replace("+", "")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif phone.startswith("7") and len(phone) == 9:
            phone = "254" + phone
        elif not phone.startswith("254"):
            phone = "254" + phone

        if len(phone) != 12:
            return jsonify({"error": "Phone must be 12 digits (2547XXXXXXXX)"}), 400

        # Get credentials from .env
        consumer_key = os.getenv('CONSUMER_KEY')
        consumer_secret = os.getenv('CONSUMER_SECRET')
        shortcode = os.getenv('SHORTCODE', '174379')
        passkey = os.getenv('PASSKEY')
        callback_url = os.getenv('CALLBACK_URL')

        if not consumer_key or not consumer_secret:
            return jsonify({"error": "Missing Consumer Key or Secret in .env"}), 500

        if not callback_url:
            return jsonify({"error": "Missing Callback URL in .env"}), 500

        # Use sandbox URL
        base_url = "https://sandbox.safaricom.co.ke"

        # Get access token
        access_token = get_access_token()
        if not access_token:
            return jsonify({"error": "Failed to get M-Pesa access token"}), 500

        # Generate password
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password_string = f"{shortcode}{passkey}{timestamp}"
        password = base64.b64encode(password_string.encode()).decode()

        # Prepare payload
        payload = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": shortcode,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": f"BinaryCash_{username}",
            "TransactionDesc": "Deposit to Binary Cash"
        }

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        print("🔄 Sending STK Push...")
        url = f"{base_url}/mpesa/stkpush/v1/processrequest"
        
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(f"[STK] Safaricom Response Status: {response.status_code}")
        print(f"[STK] Safaricom Response: {response.text}")

        result = response.json()

        if response.status_code == 200 and result.get('ResponseCode') == '0':
            return jsonify({
                "success": True,
                "message": "STK Push sent! Check your phone.",
                "data": result
            })
        else:
            error_msg = result.get('errorMessage') or result.get('ResponseDescription') or 'Unknown error'
            return jsonify({"error": error_msg}), 400

    except requests.exceptions.Timeout:
        print("[STK] Timeout error")
        return jsonify({"error": "Request timed out. Please try again."}), 408
    except Exception as e:
        print(f"[STK] Error: {str(e)}")
        return jsonify({"error": f"Failed to process payment: {str(e)}"}), 500

# ====================== M-PESA CALLBACK ======================
@app.route('/api/payments/callback', methods=['POST'])
def mpesa_callback():
    """Handle M-Pesa callback after payment"""
    try:
        # Get the callback data from M-Pesa
        callback_data = request.get_json()
        print("📞 M-Pesa Callback received:")
        print(callback_data)
        
        # Extract important information
        if callback_data and 'Body' in callback_data:
            body = callback_data['Body']
            
            # Check if it's a successful payment
            if 'stkCallback' in body:
                stk_callback = body['stkCallback']
                result_code = stk_callback.get('ResultCode')
                result_desc = stk_callback.get('ResultDesc')
                
                print(f"✅ Result Code: {result_code}")
                print(f"✅ Result Description: {result_desc}")
                
                if result_code == 0:
                    # Payment was successful
                    print("✅ Payment successful!")
                    return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200
                else:
                    # Payment failed
                    print(f"❌ Payment failed: {result_desc}")
                    return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200
            else:
                print("⚠️ No stkCallback in body")
                return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200
        else:
            print("⚠️ No Body in callback")
            return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200
            
    except Exception as e:
        print(f"❌ Callback error: {str(e)}")
        # Always return success to M-Pesa to acknowledge receipt
        return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200

# ====================== RUN APP ======================
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Binary Cash Backend running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)