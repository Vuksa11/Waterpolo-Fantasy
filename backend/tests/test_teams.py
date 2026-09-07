import uuid
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.main import app
from app.core.security import create_access_token
from db.models import Base,Competition,Season,SeasonStatus,Matchday,MatchdayStatus,Player,Position,Coach,User,Lineup,TransferHistoryEntry
import test_frontend_api as helpers

class TeamsAPI(unittest.IsolatedAsyncioTestCase):
    request = helpers.FrontendAPI.request
    tearDown = helpers.FrontendAPI.tearDown
    def setUp(self):
        self.engine=create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.session=Session(self.engine)
        self.comp=Competition(name='Test VRL',source_slug='test')
        self.user=User(email='team@example.com',display_name='Test')
        self.other_user=User(email='other@example.com',display_name='Other')
        self.session.add_all([self.comp,self.user,self.other_user]);self.session.flush()
        self.season=Season(competition_id=self.comp.id,name='Test season',status=SeasonStatus.ACTIVE,start_date=datetime.now().date(),end_date=datetime.now().date())
        self.session.add(self.season);self.session.flush()
        self.day=Matchday(season_id=self.season.id,label='Round 1',number=1,status=MatchdayStatus.UPCOMING,deadline=datetime.now(timezone.utc)+timedelta(days=1))
        self.players=[Player(competition_id=self.comp.id,name=f'P{i}',real_club='Club',position=Position(pos),current_cost=Decimal('7.10')) for i,pos in enumerate(['GK','OT','OT','OT','OT','CF','CB','GK','OT','OT','CF','CB'])]
        self.coach=Coach(competition_id=self.comp.id,name='Coach',real_club='Club',current_cost=Decimal('7.00'))
        self.session.add_all([self.day,self.coach,*self.players]);self.session.commit()
        self.token=create_access_token(self.user.id,0);self.other_token=create_access_token(self.other_user.id,0)
        async def db():yield helpers.AsyncSessionAdapter(self.session)
        app.dependency_overrides[get_db]=db

    async def create(self):
        return await self.request('/api/teams',{'competition_id':str(self.comp.id),'name':'Team','player_ids':[str(p.id) for p in self.players[:11]],'coach_id':str(self.coach.id)},token=self.token)

    async def test_owned_team_lineup_and_transfers(self):
        self.players[0].position_verified=False;self.session.commit()
        status,team=await self.create();self.assertEqual(status,201,team);self.assertEqual(team['credit_balance'],14.9);self.assertEqual(len(team['roster']),12)
        self.assertEqual(team['competition_id'],str(self.comp.id));self.assertEqual(team['version'],0)
        by_id={r['entity_id']:r for r in team['roster']}
        self.assertIs(by_id[str(self.players[0].id)]['position_verified'],False)
        self.assertIs(by_id[str(self.players[1].id)]['position_verified'],True)
        self.assertIsNone(by_id[str(self.coach.id)]['position_verified'])
        _,duplicate=await self.create();self.assertIn('already',duplicate['detail'])
        url=f"/api/teams/{team['id']}/lineup?matchday_id={self.day.id}"
        payload={'formation':'THREE_THREE','active_player_ids':[str(p.id) for p in self.players[:7]],'captain_id':str(self.players[1].id),'expected_version':0}
        status,_=await self.request(url,payload,token=self.other_token,method='PUT');self.assertEqual(status,403)
        status,_=await self.request(url,payload,method='PUT');self.assertEqual(status,401)
        status,saved=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,200,saved);self.assertEqual(saved['version'],1);self.assertEqual(len(saved['bench_player_ids']),4)
        self.assertEqual(len(list(self.session.scalars(select(Lineup)))),12)
        status,_=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,409)
        payload['expected_version']=1;payload['formation']='FOUR_TWO';payload['active_player_ids']=[str(self.players[i].id) for i in [0,1,2,3,4,5,10]]
        status,saved=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,200,saved)
        transfer={'drop_entity_type':'PLAYER','drop_entity_id':str(self.players[10].id),'add_entity_type':'PLAYER','add_entity_id':str(self.players[11].id)}
        status,updated=await self.request(f"/api/teams/{team['id']}/transfers",transfer,token=self.token);self.assertEqual(status,200,updated);self.assertEqual(updated['credit_balance'],14.9);self.assertEqual(updated['version'],3)
        self.assertEqual(len(list(self.session.scalars(select(Lineup)))),0)
        self.assertEqual(len(list(self.session.scalars(select(TransferHistoryEntry)))),2)
        payload['expected_version']=3;payload['formation']='TWO_FOUR';payload['active_player_ids']=[str(self.players[i].id) for i in [0,1,2,3,4,6,11]]
        status,saved=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,200,saved)
        status,got=await self.request(url,token=self.token);self.assertEqual(got['formation'],'TWO_FOUR');self.assertEqual(status,200)

    async def test_closed_windows_and_unknown_positions(self):
        status,team=await self.create();self.assertEqual(status,201)
        url=f"/api/teams/{team['id']}/lineup?matchday_id={self.day.id}"
        payload={'formation':'THREE_THREE','active_player_ids':[str(p.id) for p in self.players[:7]],'captain_id':str(self.players[1].id),'expected_version':0}
        self.players[0].position=None;self.session.commit()
        status,_=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,422)
        self.players[0].position=Position.GK
        for deadline in [None,datetime.now(timezone.utc)-timedelta(seconds=1)]:
            self.day.deadline=deadline;self.session.commit()
            status,_=await self.request(url,payload,token=self.token,method='PUT');self.assertEqual(status,409)
            status,_=await self.request(f"/api/teams/{team['id']}/transfers",{'drop_entity_type':'PLAYER','drop_entity_id':str(self.players[10].id),'add_entity_type':'PLAYER','add_entity_id':str(self.players[11].id)},token=self.token);self.assertEqual(status,409)
        self.assertEqual(len(list(self.session.scalars(select(Lineup)))),0)

    # Inherit only request helpers, not fixtures for catalog tests.
