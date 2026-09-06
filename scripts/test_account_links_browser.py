"""Test auth-link frontend routes against intercepted API responses; no email or DB writes."""
import os,json
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH'),headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':390,'height':844});errors=[];requests=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 def api(r):
  requests.append(r.request)
  r.fulfill(content_type='application/json',body=json.dumps({'detail':'ok'}))
 page.route('**/api/**',api)
 base=os.environ.get('FRONTEND_URL','http://localhost:3000')
 response=page.goto(base+'/verify-email?token=synthetic-verify')
 assert response.status==200 and response.headers.get('referrer-policy')=='no-referrer'
 assert 'token=' not in page.url and len(requests)==0
 page.locator('#account-link-form button').click()
 page.wait_for_timeout(150);assert 'potvrđen' in page.locator('#account-link-message').inner_text()
 assert '/auth/verify-email?token=synthetic-verify' in requests[-1].url
 page.goto(base+'/reset-password?token=synthetic-reset')
 page.evaluate("sessionStorage.setItem('vrl-token','old-session')")
 page.locator('[name="password"]').fill('password123');page.locator('[name="confirm"]').fill('password456')
 page.locator('#account-link-form button').click();assert 'ne podudaraju' in page.locator('#account-link-message').inner_text()
 before=len(requests)
 page.locator('[name="confirm"]').fill('password123');page.locator('#account-link-form button').click()
 page.wait_for_timeout(150);assert len(requests)==before+1
 assert requests[-1].post_data_json=={'token':'synthetic-reset','new_password':'password123'}
 assert page.evaluate("sessionStorage.getItem('vrl-token')") is None
 assert 'promenjena' in page.locator('#account-link-message').inner_text()
 for width in [320,390,768,1440]:
  page.set_viewport_size({'width':width,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.goto(base+'/reset-password');assert page.locator('#account-link-form button').is_disabled()
 assert not errors,errors
 print('PASS account links: routes, no automatic verification, hidden query, referrer policy, password confirmation, API payload, local logout, mobile widths, missing token')
 b.close()
