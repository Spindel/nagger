import uuid

from oauthlib.oauth2 import WebApplicationClient
import requests

from structlog import get_logger

_log = get_logger(__name__)


def get_webserver_response(authorization_url, redirect_url):
    """Launch webserver and make request.

    Launch a web server on redirect_url, then open a browser to
    authorization_url,  and listen until we get a code
    response.
    """
    import http.server
    import webbrowser
    import urllib.parse

    response = None

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        """Handle GET request, succesfully."""

        def do_GET(self):
            nonlocal response
            if "code=" in self.path:
                response = self.path
            self.send_response(200, message="OK")
            self.end_headers()

    _listen = urllib.parse.urlparse(redirect_url)
    host, port = _listen.hostname, _listen.port

    while response is None:
        with http.server.HTTPServer((host, port), OAuthHandler) as httpd:
            print("Please visit", authorization_url)
            # open it in a new tab
            webbrowser.open(authorization_url, new=2)
            httpd.handle_request()
    return response


class GLOauth:
    """enough state to get an oauth token from gitlab."""

    SCOPES = ["api"]
    CLIENT_ID = "bf556db1755e8c6d13aaef733dd66c5fdaf4380318ca3cac232230726094f384"
    AUTH_URL = "https://gitlab.com/oauth/authorize"
    TOKEN_URL = "https://gitlab.com/oauth/token"
    INFO_URL = "https://gitlab.com/oauth/token/info"

    REDIRECT_URI = "http://localhost:8000"

    def __init__(self):
        self.session = requests.Session()
        self.state = uuid.uuid4().hex
        self.client = WebApplicationClient(client_id=self.CLIENT_ID)

    def step_get_code(self):
        magic_url = self.client.prepare_request_uri(
            self.AUTH_URL,
            redirect_uri=self.REDIRECT_URI,
            scope=self.SCOPES,
            state=self.state,
        )
        response = get_webserver_response(magic_url, self.REDIRECT_URI)
        # Response contains only the "/code=....." part. Pad with
        # https://localhost to make the parsing library happy
        fake_url = "https://localhost" + response
        parsed = self.client.parse_request_uri_response(fake_url, state=self.state)
        code = parsed["code"]
        return code

    def step_get_token(self, code):
        """Perform the second step, grabbing a token from a code."""
        # params = {
        #    "grant_type": "authorization_code",
        #    "client_id": self.CLIENT_ID,
        #    "redirect_uri": self.REDIRECT_URI,
        # }
        # Log here
        # params["code"] = code
        # resp = self.session.post(self.TOKEN_URL, params=params)
        body = self.client.prepare_request_body(
            code=code, redirect_uri=self.REDIRECT_URI
        )
        resp = self.session.post(self.TOKEN_URL, body)
        data = resp.json()
        if not resp.ok:
            _log.error(f"Error from server(remove ~/.netrc?): {data}")
            resp.raise_for_status()
        return data["access_token"]

    def get_token(self):
        code = self.step_get_code()
        token = self.step_get_token(code)
        return token

    def get_token_info(self, token):
        params = {
            "access_token": token,
        }
        resp = self.session.get(self.INFO_URL, params=params)
        data = resp.json()
        if not resp.ok:
            _log.error(f"Error from server(remove ~/.netrc?): {data}")
            resp.raise_for_status()
        return data
