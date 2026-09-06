"""Frontend browser contract test. Requires Playwright and a running frontend.
API requests are intercepted; no business data is written to a server.
Set CHROMIUM_PATH when using an existing Chromium binary.
"""
import json, os, subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
root = Path(__file__).resolve().parents[1]
fixture_script = "import {demoDraft,demoPlayers,demoMatches,demoStandings} from './frontend/src/demo.js'; process.stdout.write(JSON.stringify({demoDraft,demoPlayers,demoMatches,demoStandings}));"
f=json.loads(subprocess.check_output(['node','--input-type=module','-e',fixture_script],cwd=root))
d=f['demoDraft'];state={'saved':None,'created':False,'requests':[],'transferkeys':[],'failtransfer':True}
roster=[dict(entity_type='PLAYER',entity_id=p['id'],name=p['name'],position=p['position'],real_club=p['real_club'],current_cost=p['current_cost'],purchase_price=p['current_cost']) for p in d['roster']]
roster.append(dict(entity_type='COACH',entity_id='coach',name='Test trener',position=None,real_club='Test',current_cost=7,purchase_price=7))
team=dict(id='team1',competition_id='league',name='Test tim',credit_balance=10.5,version=0,roster=roster)
day=dict(id='day',label='Final',number=9300,status='UPCOMING',deadline='2030-01-01T12:00:00Z')
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH'),headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':390,'height':844}); errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 def route(r):
  req=r.request;path=urlparse(req.url).path;state['requests'].append(path)
  payload={};status=200
  if path=='/api/auth/register':payload={'access_token':'test-token'}
  elif path=='/api/auth/me':payload={'id':'user1','email':'test@example.com','display_name':'Test'}
  elif path=='/api/competitions':payload=[{'id':'league','name':'Test liga'}]
  elif path=='/api/home':payload={'selected_matchday':day,'matches':f['demoMatches'],'standings_top4':f['demoStandings'][:4],'updated_at':None}
  elif path.endswith('/matchdays'):payload=[day]
  elif path.endswith('/leaderboard'):
   offset=int(parse_qs(urlparse(req.url).query).get('offset',['0'])[0])
   payload={'competition_id':'league','league_id':'global','total':27,'limit':25,'offset':offset,'entries':[{'rank':i+1,'team_id':str(i),'team_name':'<b>Tim</b> '+str(i+1),'owner_display_name':'Menadžer sa veoma dugim imenom za mobilni prikaz','total_points':0} for i in range(offset,min(offset+25,27))]}
  elif path.endswith('/standings'):payload=f['demoStandings']
  elif path.endswith('/facets'):payload={'clubs':[],'positions':['GK','OT','CF','CB']}
  elif path=='/api/coaches':payload=[{'id':'coach','name':'Test trener','real_club':'Test','current_cost':7}]
  elif path=='/api/teams/me':payload=[team] if state['created'] else []
  elif path=='/api/players/catalog':payload={'items':f['demoPlayers'],'total':len(f['demoPlayers']),'offset':0,'limit':24}
  elif path=='/api/lineups/validate':payload={'valid':True}
  elif path=='/api/teams' and req.method=='POST':state['created']=True;payload=team;assert req.headers.get('idempotency-key')
  elif path.endswith('/lineup'):
   if req.method=='PUT':
    state['saved']={**req.post_data_json,'version':1};team['version']=1
   payload=state['saved'] or {'formation':None,'active_player_ids':[],'captain_id':None,'version':0}
  elif path.endswith('/transfers'):
   state['transferkeys'].append(req.headers.get('idempotency-key'))
   if state['failtransfer']:
    state['failtransfer']=False;r.abort();return
   data=req.post_data_json;new=next(x for x in f['demoPlayers'] if x['id']==data['add_entity_id'])
   team['roster']=[x for x in team['roster'] if x['entity_id']!=data['drop_entity_id']]+[dict(entity_type='PLAYER',entity_id=new['id'],name=new['name'],position=new['position'],real_club=new['real_club'],current_cost=new['current_cost'])]
   payload=team
  else:status=404;payload={'detail':'missing test route '+path}
  r.fulfill(status=status,content_type='application/json',body=json.dumps(payload))
 page.route('**/api/**',route)
 page.goto(os.environ.get('FRONTEND_URL','http://localhost:3000'),wait_until='networkidle')
 page.locator('[data-mode="api"]').click();page.wait_for_timeout(300)
 page.locator('#account').click();page.locator('#switch-auth').click()
 page.locator('[name="display_name"]').fill('Test');page.locator('[name="email"]').fill('test@example.com');page.locator('[name="password"]').fill('password123');page.locator('#auth-form button').click();page.wait_for_timeout(400)
 # Restore a complete user's draft to exercise validated API writes with confirmed positions.
 seeded={**d,'coach':{'id':'coach','name':'Test trener','current_cost':7}}
 page.evaluate('(d)=>localStorage.setItem("vrl-draft-v2:api:league:user1",JSON.stringify(d))',seeded)
 page.reload(wait_until='networkidle');page.locator('nav [data-go="team"]').click()
 assert 'Finale' in page.locator('.round-number').inner_text();assert '9300' not in page.locator('.round-number').inner_text()
 page.locator('.mobile-team-action button').click();page.wait_for_timeout(400)
 assert state['created'] and state['saved'];assert 'sačuvan' in page.locator('#toast').inner_text()
 page.reload(wait_until='networkidle');assert page.locator('.pool-player.filled').count()==7
 page.locator('nav [data-go="players"]').click();page.wait_for_timeout(200)
 page.locator('[data-buy="13"]').click();page.locator('#outgoing').select_option('12');page.locator('#transfer-form button').click();page.wait_for_timeout(200)
 assert 'Ishod' in page.locator('#transfer-error').inner_text()
 page.locator('#transfer-form button').click();page.wait_for_timeout(200)
 assert len(state['transferkeys'])==2 and state['transferkeys'][0]==state['transferkeys'][1]
 page.locator('nav [data-go="home"]').click();page.locator('nav [data-go="players"]').click();page.wait_for_timeout(200)
 count=state['requests'].count('/api/players/catalog')
 page.locator('nav [data-go="home"]').click();page.locator('nav [data-go="players"]').click();page.wait_for_timeout(100)
 assert state['requests'].count('/api/players/catalog')==count
 assert '/api/home' in state['requests'];assert not errors,errors
 page.locator('nav [data-go="standings"]').click();page.locator('[data-ranking="fantasy"]').click();page.wait_for_timeout(200)
 assert page.locator('.fantasy-table tbody tr').count()==25
 assert page.locator('.fantasy-table tbody tr').first.inner_text().find('<b>Tim</b>')>=0
 assert 'u pripremi' in page.locator('.notice').inner_text()
 page.locator('#ranking-next').click();page.wait_for_timeout(200)
 assert page.locator('.fantasy-table tbody tr').count()==2
 assert page.locator('#ranking-next').is_disabled()
 page.locator('#ranking-prev').click();page.wait_for_timeout(100)
 for width in [320,390,768,1440]:
  page.set_viewport_size({'width':width,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
  assert page.locator('.fantasy-table').evaluate('(el)=>el.getBoundingClientRect().right <= innerWidth'),width
 page.set_viewport_size({'width':390,'height':844})
 page.screenshot(path='/tmp/vrl-fantasy-ranking-mobile.png',full_page=True)
 print('PASS ranking pagination/mobile/escaped names and mocked API contract: registration, team create, lineup save/reload, Final label, uncertain transfer retry same key, catalog cache, no JS errors')
 b.close()
