import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from db.models import Base
from scraper.db_writer import get_or_create_competition,get_or_create_active_season,get_or_create_matchday,upsert_fixture
from scraper.parsers.schedule_page import ScrapedFixture,ScrapedTeamRef

class FixtureUpdate(unittest.TestCase):
 def test_existing_match_moves_to_correct_round(self):
  engine=create_engine('sqlite://')
  Base.metadata.create_all(engine)
  with Session(engine) as session:
   competition=get_or_create_competition(session,1)
   season=get_or_create_active_season(session,competition)
   old=get_or_create_matchday(session,season,'Semifinal')
   new=get_or_create_matchday(session,season,'Final')
   fixture=ScrapedFixture(123,'Semifinal',ScrapedTeamRef(1,'A'),ScrapedTeamRef(2,'B'),1,2,'FINISHED',None)
   match=upsert_fixture(session,old,fixture)
   fixture.round_label='Final'
   updated=upsert_fixture(session,new,fixture)
   self.assertEqual(match.id,updated.id)
   self.assertEqual(updated.matchday_id,new.id)
  engine.dispose()
