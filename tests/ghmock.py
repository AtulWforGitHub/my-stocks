"""Stand-in for GitHub (contents API + the Pages site) used by the browser tests. The real GitHub is never contacted."""
import base64, json

CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "authorization,content-type,x-github-api-version", "access-control-allow-methods": "GET,PUT,OPTIONS"}


class Mock:
    def __init__(self, html, site="https://user.github.io/repo/", token="tok"):
        self.html, self.site, self.token = html, site, token
        self.files = {}          # file name -> {"b64": str, "sha": int}
        self.puts, self.bodies = 0, []

    def text(self, name):
        return base64.b64decode(self.files[name]["b64"]).decode()

    def install(self, ctx):
        ctx.route("**/*", self._handler)

    def _handler(self, route):
        req, u = route.request, route.request.url
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        if u.startswith(self.site):
            rest = u[len(self.site):].split("?")[0].split("#")[0]
            if rest in ("", "index.html"):
                return route.fulfill(status=200, content_type="text/html", body=self.html)
            if rest in ("holdings.json", "holdings.enc.json"):
                f = self.files.get(rest)
                return route.fulfill(status=404, body="") if not f else route.fulfill(status=200, content_type="application/json", body=self.text(rest))
            return route.fulfill(status=404, body="")
        if u == "https://api.github.com/repos/user/repo":
            return route.fulfill(status=200, headers=CORS, content_type="application/json", body='{"full_name":"user/repo"}')
        if u.startswith("https://api.github.com/repos/user/repo/contents/docs/"):
            name = u.split("/contents/docs/")[1].split("?")[0]
            if req.headers.get("authorization") != "Bearer " + self.token:
                return route.fulfill(status=401, headers=CORS, body="{}")
            f = self.files.get(name)
            if req.method == "GET":
                if not f: return route.fulfill(status=404, headers=CORS, content_type="application/json", body='{"message":"Not Found"}')
                return route.fulfill(status=200, headers=CORS, content_type="application/json", body=json.dumps({"sha": f"sha{f['sha']}", "content": f["b64"]}))
            b = json.loads(req.post_data)
            if (f and b.get("sha") != f"sha{f['sha']}") or (not f and b.get("sha")):
                return route.fulfill(status=409, headers=CORS, content_type="application/json", body="{}")
            sha = (f["sha"] + 1) if f else 1
            self.files[name] = {"b64": b["content"], "sha": sha}; self.puts += 1; self.bodies.append((name, base64.b64decode(b["content"]).decode()))
            return route.fulfill(status=200, headers=CORS, content_type="application/json", body=json.dumps({"content": {"sha": f"sha{sha}"}}))
        route.continue_()
