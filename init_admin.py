import os,sys,pymysql
from werkzeug.security import generate_password_hash
c=pymysql.connect(host='127.0.0.1',user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],database='security_assets',autocommit=True)
with c.cursor() as x:x.execute("INSERT INTO users(username,password_hash,display_name,role) VALUES(%s,%s,%s,'admin')",(sys.argv[1],generate_password_hash(sys.argv[3]),sys.argv[2]))