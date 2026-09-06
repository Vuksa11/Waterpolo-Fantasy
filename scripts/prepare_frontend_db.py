"""Create an isolated frontend development DB with a sports-only source snapshot.
Does not copy accounts or modify the source DB. Run once before local preview.
"""
import os
import secrets
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'backend')]
from db.models import Base
SOURCE=os.environ.get('FRONTEND_SOURCE_DB','postgresql://waterpolo:waterpolo@127.0.0.1:5432/waterpolo_fantasy')
TARGET_NAME='waterpolo_fantasy_frontend'
from sqlalchemy.engine import make_url
password=(Path(os.environ.get('VRL_PG_HOME',str(Path.home()/'.cache/vrl-fantasy-postgres')))/'password').read_text().strip()
target=make_url(SOURCE).set(host='127.0.0.1',port=55432,database=TARGET_NAME,password=password)
admin=psycopg2.connect(target.set(database='postgres').render_as_string(hide_password=False));admin.autocommit=True
with admin.cursor() as cur:
    cur.execute('SELECT 1 FROM pg_database WHERE datname=%s',(TARGET_NAME,))
    if not cur.fetchone():cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(TARGET_NAME)))
admin.close()
from sqlalchemy.engine import make_url
url=target.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False)
env=ROOT/'.env'
if not env.exists():env.write_text('DATABASE_URL='+url+'\nJWT_SECRET='+secrets.token_urlsafe(48)+'\nENVIRONMENT=development\n');env.chmod(0o600)
# Explicit environment controls migrations without relying on another checkout.
runenv=dict(os.environ,DATABASE_URL=url,PYTHONPATH=str(ROOT/'backend')+':'+str(ROOT))
subprocess.run([sys.executable,'-m','alembic','-c','alembic.ini','upgrade','head'],cwd=ROOT/'backend',env=runenv,check=True)
source=create_engine(SOURCE);dest=create_engine(target)
counts={}
with source.connect() as src,dest.begin() as dst:
    for name in ['competitions','players','coaches','seasons','matchdays','matches','player_stats','coach_stats','fantasy_scores','price_history']:
        table=Base.metadata.tables[name]
        rows=[dict(row._mapping) for row in src.execute(select(table))]
        for start in range(0,len(rows),100):dst.execute(insert(table).values(rows[start:start+100]).on_conflict_do_nothing())
        counts[name]=len(rows)
print('Sports snapshot copied into isolated database:',TARGET_NAME,counts)
(ROOT/'frontend'/'DATA_SOURCE.md').write_text('# Lokalni sportski podaci\n\nAPI preview koristi zasebnu bazu `'+TARGET_NAME+'`. Sportski snapshot preuzet '+datetime.now(timezone.utc).isoformat()+'.\n\nKorisnički nalozi nisu kopirani. Originalna main baza nije menjana. Ovo nije live sinhronizacija; seed skripta dodaje nedostajuće redove i ne prepisuje postojeće.\n')
