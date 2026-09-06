"""Real PostgreSQL + HTTP + browser smoke. ONLY isolated frontend DB; cleans its fixtures."""
from pathlib import Path
import sys,uuid,concurrent.futures
from datetime import datetime,timedelta,timezone
from decimal import Decimal
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parents[1])]
from app.core.config import settings
from db.models import *
from sqlalchemy import create_engine,select,delete
from sqlalchemy.orm import Session
import urllib.request, urllib.error, json
class Response:
 def __init__(self,code,body):self.status_code=code;self.text=body.decode()
 def json(self):return json.loads(self.text)
class HTTP:
 def call(self,method,url,headers=None,json=None,timeout=20):
  data=__import__('json').dumps(json).encode() if json is not None else None
  req=urllib.request.Request(url,data=data,headers={**(headers or {}),'Content-Type':'application/json'},method=method)
  try:
   with urllib.request.urlopen(req,timeout=timeout) as r:return Response(r.status,r.read())
  except urllib.error.HTTPError as r:return Response(r.code,r.read())
 def get(self,url,**kw):return self.call('GET',url,**kw)
 def post(self,url,**kw):return self.call('POST',url,**kw)
 def put(self,url,**kw):return self.call('PUT',url,**kw)
requests=HTTP()
from playwright.sync_api import sync_playwright
assert settings.database_url.endswith('/waterpolo_fantasy_frontend'), 'Never test mutations on source DB'
engine=create_engine(settings.database_url.replace('+asyncpg','+psycopg2'))
base='http://127.0.0.1:3002/api'
run=uuid.uuid4().hex[:10];comp_id=uuid.uuid4();test_email=f'qa-{run}@example.com';password='test-Fantasy-1234';user_id=None
with Session(engine) as s:
 c=Competition(id=comp_id,name='QA Synthetic '+run,source_slug='qa-'+run);s.add(c);s.flush()
 season=Season(competition_id=c.id,name='QA',status=SeasonStatus.ACTIVE,start_date=datetime.now().date(),end_date=datetime.now().date());s.add(season);s.flush()
 day=Matchday(season_id=season.id,label='QA Round 1',number=1,status=MatchdayStatus.UPCOMING,deadline=datetime.now(timezone.utc)+timedelta(days=1));s.add(day)
 ps=[Player(competition_id=c.id,name=f'QA Player {i}',real_club='QA Club',position=Position(role),current_cost=Decimal('7.10')) for i,role in enumerate(['GK','OT','OT','OT','OT','CF','CB','GK','OT','OT','CF','CB','CF'])]
 coach=Coach(competition_id=c.id,name='QA Coach',real_club='QA Club',current_cost=Decimal('7'))
 s.add_all([coach,*ps]);s.commit()
 seed=[{'id':str(p.id),'name':p.name,'position':p.position.value,'real_club':p.real_club,'current_cost':float(p.current_cost)} for p in ps]
 coach_seed={'id':str(coach.id),'name':coach.name,'current_cost':float(coach.current_cost)};day_id=str(day.id)
try:
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  regs=list(pool.map(lambda _:requests.post(base+'/auth/register',json={'email':test_email,'password':password,'display_name':'QA Player'},timeout=20),range(2)))
 assert sorted(r.status_code for r in regs)==[201,409],[(r.status_code,r.text) for r in regs]
 token=next(r.json()['access_token'] for r in regs if r.status_code==201);headers={'Authorization':'Bearer '+token};user_id=requests.get(base+'/auth/me',headers=headers).json()['id']
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path='/home/vuksa/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless=True,args=['--no-sandbox']);page=b.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://127.0.0.1:3002',wait_until='networkidle');page.locator('#account').click();page.locator('[name="email"]').fill(test_email);page.locator('[name="password"]').fill(password);page.locator('#auth-form button').click();page.wait_for_function("sessionStorage.getItem('vrl-token') !== null");page.wait_for_timeout(500)
  draft={'name':'QA Team','formation':'THREE_THREE','roster':seed[:11],'active':[d['id'] for d in seed[:7]],'captain':seed[1]['id'],'coach':coach_seed,'savedAt':None}
  page.evaluate("([k,v])=>localStorage.setItem(k,JSON.stringify(v))",[f'vrl-draft-v2:api:{comp_id}:{user_id}',draft])
  page.locator('[data-mode="api"]').click();page.wait_for_selector('#competition option[value="'+str(comp_id)+'"]',state='attached');page.locator('#competition').select_option(str(comp_id));page.wait_for_timeout(1000)
  page.locator('nav [data-go="team"]').click();page.locator('#save-lineup').click();page.wait_for_function("document.querySelector('#toast').textContent.includes('sačuvan na serveru')")
  teams=requests.get(base+'/teams/me',headers=headers).json();team=teams[0];tid=team['id']
  assert len(team['roster'])==12 and team['version']==1,team
  page.locator('[data-slot="2"]').click();page.locator('#captain').click();page.locator('#save-lineup').click();page.wait_for_timeout(500)
  lineup=requests.get(base+f'/teams/{tid}/lineup?matchday_id={day_id}',headers=headers).json();assert lineup['captain_id']==seed[2]['id'],lineup
  assert set(lineup['active_player_ids'])==set(draft['active'])
  # Two simultaneous saves with the same version: exactly one succeeds.
  body={'formation':'THREE_THREE','active_player_ids':draft['active'],'captain_id':seed[2]['id'],'expected_version':lineup['version']}
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   saves=list(pool.map(lambda _:requests.put(base+f'/teams/{tid}/lineup?matchday_id={day_id}',headers=headers,json=body,timeout=20),range(2)))
  assert sorted(r.status_code for r in saves)==[200,409],[r.text for r in saves]
  transfer={'drop_entity_type':'PLAYER','drop_entity_id':seed[10]['id'],'add_entity_type':'PLAYER','add_entity_id':seed[12]['id']}
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   transfers=list(pool.map(lambda _:requests.post(base+f'/teams/{tid}/transfers',headers=headers,json=transfer,timeout=20),range(2)))
  assert sorted(r.status_code for r in transfers)==[200,422],[r.text for r in transfers]
  updated=requests.get(base+'/teams/me',headers=headers).json()[0];assert updated['credit_balance']==14.9,updated
  page.locator('nav [data-go="players"]').click();page.wait_for_timeout(600);assert page.locator('tbody tr').count()==13
  page.locator('[data-mode="demo"]').click();page.locator('nav [data-go="team"]').click();page.set_viewport_size({'width':390,'height':844});page.screenshot(path='/tmp/vrl-final-mobile.png',full_page=True)
  assert not errors,errors;b.close()
 print('PASS real PostgreSQL/browser: login, scoped API, team create, saved captain/lineup, duplicate-registration race, version race (200/409), transfer race (200/422), exact budget14.90, paginated catalog.')
finally:
 with Session(engine) as s:
  season_ids=select(Season.id).where(Season.competition_id==comp_id)
  team_ids=select(FantasyTeam.id).where(FantasyTeam.season_id.in_(season_ids))
  for model in [Lineup,Roster,TransferHistoryEntry]:s.execute(delete(model).where(model.fantasy_team_id.in_(team_ids)))
  s.execute(delete(FantasyTeam).where(FantasyTeam.season_id.in_(season_ids)))
  s.execute(delete(League).where(League.season_id.in_(season_ids)))
  s.execute(delete(Matchday).where(Matchday.season_id.in_(season_ids)))
  for model in [Player,Coach,Season]:s.execute(delete(model).where(model.competition_id==comp_id))
  s.execute(delete(Competition).where(Competition.id==comp_id));s.execute(delete(User).where(User.email==test_email));s.commit()
