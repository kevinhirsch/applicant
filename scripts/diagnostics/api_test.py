import sys, json, urllib.request, urllib.parse, http.cookiejar
BASE, USER, PW = sys.argv[1], sys.argv[2], sys.argv[3]
cj=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open(urllib.request.Request(BASE+"/login",data=urllib.parse.urlencode({"username":USER,"password":PW,"next":"/"}).encode(),headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read()
TOK=json.load(op.open(urllib.request.Request(BASE+"/api/csrf_token"),timeout=10)).get("token","")
def ep(p,d):
    try:
        r=op.open(urllib.request.Request(BASE+p,data=json.dumps(d).encode(),headers={"Content-Type":"application/json","X-CSRF-Token":TOK}),timeout=12)
        return f"{r.status} {r.read()[:90]!r}"
    except Exception as e: return f"{getattr(e,'code','ERR')} {str(e)[:60]}"
print("WRONG  /api/campaigns                     :", ep("/api/campaigns",{"action":"list"}))
print("RIGHT  /api/plugins/applicant/campaigns   :", ep("/api/plugins/applicant/campaigns",{"action":"list"}))
print("RIGHT  /api/plugins/applicant/mind        :", ep("/api/plugins/applicant/mind",{"action":"list"}))
