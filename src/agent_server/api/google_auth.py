import os
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8002/auth/google/callback")

@router.get("/auth/google/login")
async def google_login():
    """Redirects user to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google Client ID/Secret not configured.")

    scope = (
        "https://www.googleapis.com/auth/calendar "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/userinfo.email"
    )
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return RedirectResponse(auth_url)

@router.get("/auth/google/callback")
async def google_callback(code: str):
    """Exchanges code for tokens and returns HTML to close popup."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google Client ID/Secret not configured.")
        
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=payload)
        
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to get token: {response.text}")
        
    data = response.json()
    refresh_token = data.get("refresh_token")
    access_token = data.get("access_token")
    
    if not refresh_token:
        # If user has already granted access, Google might not return refresh token unless we revoke first or force prompt.
        # We used prompt=consent, so it should be there.
        pass

    # Return HTML that sends data to parent window
    html_content = f"""
    <html>
        <head>
            <title>Authentication Successful</title>
        </head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h3>Authentication Successful</h3>
            <p>You can close this window.</p>

            <script>
                const data = {{
                    refresh_token: "{refresh_token}",
                    access_token: "{access_token}",
                    client_id: "{GOOGLE_CLIENT_ID}",
                    client_secret: "{GOOGLE_CLIENT_SECRET}"
                }};
                
                // Send data to parent window safely
                if (window.opener) {{
                    window.opener.postMessage({{ type: "GOOGLE_AUTH_SUCCESS", data: data }}, "*");
                    setTimeout(() => window.close(), 1000); // Close quicker
                }} else {{
                    document.write("<p>Please close this window and return to the application.</p>");
                }}
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)
