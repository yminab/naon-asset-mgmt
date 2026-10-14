import os,json,re
from io import BytesIO
from functools import wraps
from flask import Flask,render_template,request,redirect,session,flash,abort,jsonify,send_file
import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash,generate_password_hash
from openpyxl import Workbook,load_workbook
app=Flask(__name__);app.secret_key=os.environ.get('SECRET_KEY','x')
ROLE_LABEL={'admin':'관리자','oper':'운용자','user':'사용자'}
def conn():return pymysql.connect(host='127.0.0.1',user=os.environ.get('DB_USER','securityweb'),password=os.environ.get('DB_PASSWORD',''),database='security_assets',charset='utf8mb4',cursorclass=DictCursor,autocommit=True)
def q(s,a=(),one=False):
 c=conn()
 try:
  with c.cursor() as x:x.execute(s,a);return x.fetchone() if one else x.fetchall()
 finally:c.close()
def ex(s,a=()):
 c=conn()
 try:
  with c.cursor() as x:x.execute(s,a);return x.lastrowid
 finally:c.close()
@app.context_processor
def ctx():return dict(role_label=lambda r:ROLE_LABEL.get(r,r))
@app.before_request
def before():
 request.user=q('SELECT * FROM users WHERE id=%s AND enabled=1',(session.get('uid'),),True) if session.get('uid') else None
 if request.user:ex('UPDATE users SET last_seen_at=NOW() WHERE id=%s',(request.user['id'],))
def login_req(f):
 @wraps(f)
 def w(*a,**k):return redirect('/login') if not request.user else f(*a,**k)
 return w
def roles(*rs):
 def d(f):
  @wraps(f)
  @login_req
  def w(*a,**k):
   if request.user['role'] not in rs:abort(403)
   return f(*a,**k)
  return w
 return d
def fullasset(i):return q('SELECT a.*,p.name purpose,p.server_target FROM assets a JOIN purposes p ON p.id=a.purpose_id WHERE a.id=%s',(i,),True)
def snap(a):
 if not a:return None
 ks=['asset_no','asset_type','asset_class','asset_name','purpose','assignee','location','manufacturer','model_name','serial_no','purchase_date','quantity','mac_address','os_name','ip_address','port_info','monthly_check','eval_c','eval_i','eval_a','eval_r','enabled'];return {k:a.get(k) for k in ks}
def audit(action,etype,eid,name,b=None,a=None,reason=None,no=None):ex('INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,entity_name,asset_no,before_data,after_data,reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(request.user['id'],action,etype,eid,name,no or ((a or b or {}).get('asset_no') if isinstance(a or b,dict) else None),json.dumps(b,ensure_ascii=False,default=str) if b is not None else None,json.dumps(a,ensure_ascii=False,default=str) if a is not None else None,reason))
def erange():
 d={x['key']:int(x['value']) for x in q('SELECT * FROM settings')};return range(d['eval_min'],d['eval_max']+1)
def specs(i):return q('SELECT * FROM sample_specs WHERE asset_id=%s ORDER BY FIELD(spec_type,\'CPU\',\'MEM\',\'DISK\',\'NIC\',\'PSU\',\'ETC\'),id',(i,))
def save_specs(i):
 ex('DELETE FROM sample_specs WHERE asset_id=%s',(i,))
 if request.form.get('asset_type')!='hardware':return
 for typ in ['CPU','MEM','DISK','NIC','PSU','ETC']:
  models=request.form.getlist('spec_model_'+typ);qtys=request.form.getlist('spec_qty_'+typ)
  for m,n in zip(models,qtys):
   m=m.strip()
   if m:ex('INSERT INTO sample_specs(asset_id,spec_type,model_name,quantity) VALUES(%s,%s,%s,%s)',(i,typ,m,max(1,int(n or 1))))
def licenses(i):return q('SELECT id,asset_id,license_code,enabled,created_at FROM software_licenses WHERE asset_id=%s ORDER BY id',(i,))
def save_licenses(i):
 ex('DELETE FROM software_licenses WHERE asset_id=%s AND id NOT IN (SELECT license_id FROM software_license_assignments WHERE returned_date IS NULL)',(i,))
 if request.form.get('asset_type')!='software':return
 for code in request.form.getlist('license_code'):
  if code.strip():ex('INSERT INTO software_licenses(asset_id,license_code) VALUES(%s,%s) ON DUPLICATE KEY UPDATE enabled=1',(i,code.strip()))
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  u=q('SELECT * FROM users WHERE username=%s AND enabled=1',(request.form['username'],),True)
  if u and check_password_hash(u['password_hash'],request.form['password']):session['uid']=u['id'];ex('UPDATE users SET last_login_at=NOW(),last_seen_at=NOW(),last_logout_at=NULL WHERE id=%s',(u['id'],));return redirect('/assets')
  flash('로그인 정보를 확인하세요.','danger')
 return render_template('login.html')
@app.get('/logout')
def logout():
 if session.get('uid'):ex('UPDATE users SET last_logout_at=NOW() WHERE id=%s',(session['uid'],))
 session.clear();return redirect('/login')
@app.get('/')
@login_req
def root():return redirect('/assets')
@app.get('/assets')
@login_req
def assets():
 wh=[];args=[]
 keyword=request.args.get('q','').strip();purpose=request.args.get('purpose','');aclass=request.args.get('class','');atype=request.args.get('type','');assignee=request.args.get('assignee','');location=request.args.get('location','');enabled=request.args.get('enabled','');monthly=request.args.get('monthly','')
 if keyword:wh.append('(a.asset_no LIKE %s OR a.asset_name LIKE %s OR a.serial_no LIKE %s OR a.model_name LIKE %s OR a.manufacturer LIKE %s OR a.ip_address LIKE %s OR a.mac_address LIKE %s)');args += ['%'+keyword+'%']*7
 if purpose:wh.append('a.purpose_id=%s');args.append(int(purpose))
 if aclass:wh.append('a.asset_class=%s');args.append(aclass)
 if atype:wh.append('a.asset_type=%s');args.append(atype)
 if assignee:wh.append('a.assignee=%s');args.append(assignee)
 if location:wh.append('a.location=%s');args.append(location)
 
 if enabled=='deleted':wh.append('a.deleted_at IS NOT NULL')
 elif enabled in ('0','1'):wh.append('a.deleted_at IS NULL AND a.enabled=%s');args.append(int(enabled))
 else:wh.append('a.deleted_at IS NULL')
 if monthly in ('0','1'):wh.append('a.monthly_check=%s');args.append(int(monthly))
 sql="SELECT a.*,p.name purpose,p.server_target,(SELECT COUNT(*) FROM software_license_assignments sa WHERE sa.asset_id=a.id AND sa.returned_date IS NULL) sw_used FROM assets a JOIN purposes p ON p.id=a.purpose_id WHERE "+' AND '.join(wh)+' ORDER BY a.id DESC'
 return render_template('assets.html',rows=q(sql,args),purposes=q('SELECT * FROM purposes WHERE enabled=1 ORDER BY name'),assignees=q("SELECT DISTINCT assignee v FROM assets WHERE deleted_at IS NULL AND assignee<>'' ORDER BY assignee"),locations=q("SELECT DISTINCT location v FROM assets WHERE deleted_at IS NULL AND location IS NOT NULL AND location<>'' ORDER BY location"))
def formdata():
 t=request.form.get('asset_type','hardware');cl=request.form.get('asset_class','normal');name=request.form.get('asset_name','').strip();user=request.form.get('assignee','').strip()
 if t=='software':
  sp=q("SELECT id FROM purposes WHERE name='소프트웨어' AND enabled=1 ORDER BY id LIMIT 1",one=True)
  if not sp:abort(400,'소프트웨어 용도 규칙이 없습니다.')
  pid=int(sp['id']);cl='normal'
 else:
  pid_raw=request.form.get('purpose_id')
  if not pid_raw:abort(400,'용도를 선택하세요.')
  pid=int(pid_raw)
 if t not in ('hardware','software') or cl not in ('normal','sample') or not name or not user:abort(400)
 d={'asset_type':t,'asset_class':cl,'asset_name':name,'purpose_id':pid,'assignee':user,'location':request.form.get('location') or None,'quantity':int(request.form.get('quantity') or 0) if t=='software' else None,'monthly_check':1 if request.form.get('monthly_check') else 0,'enabled':int(request.form['enabled'])}
 if t=='software':d['purpose_id']=pid;d['asset_class']='normal';d['quantity']=max(0,int(request.form.get('quantity') or 0))
 for k in ['manufacturer','model_name','serial_no','purchase_date','mac_address','os_name','ip_address','port_info']:d[k]=request.form.get(k) or None
 if t=='software':
  d['mac_address']=d['os_name']=d['ip_address']=d['port_info']=None;d['monthly_check']=0
 for k in ['eval_c','eval_i','eval_a','eval_r']:d[k]=int(request.form[k]) if request.form.get(k) else None
 return d
@app.route('/assets/new',methods=['GET','POST'])
@roles('admin')
def anew():
 if request.method=='POST':
  d=formdata();d['enabled']=0 if request.form.get('asset_state')=='unused' else 1;p=q('SELECT * FROM purposes WHERE id=%s AND enabled=1',(d['purpose_id'],),True) or abort(400);seq=int(p['next_sequence']);d['asset_no']=f"{p['asset_prefix']}-{seq:03d}";cs=list(d);i=ex('INSERT INTO assets('+','.join(cs)+') VALUES('+','.join(['%s']*len(cs))+')',[d[k] for k in cs]);ex('UPDATE purposes SET next_sequence=next_sequence+1 WHERE id=%s',(p['id'],));save_specs(i);save_licenses(i);a=fullasset(i);audit('추가','asset',i,a['asset_name'],a=snap(a));return redirect('/assets')
 return render_template('asset_form.html',asset=None,purposes=q('SELECT * FROM purposes WHERE enabled=1'),locations=q('SELECT * FROM locations WHERE enabled=1 ORDER BY display_order,name'),ev=erange(),specs=[],licenses=[])
@app.route('/assets/<int:i>/edit',methods=['GET','POST'])
@roles('admin','oper')
def aedit(i):
 old=fullasset(i) or abort(404)
 if request.method=='POST':
  state=request.form.get('asset_state','use')
  if state=='deleted':
   reason=request.form.get('delete_reason','').strip()
   if not reason:flash('삭제 사유를 입력하세요.','danger');return redirect(f'/assets/{i}/edit')
   ex('UPDATE assets SET deleted_at=NOW(),enabled=0 WHERE id=%s',(i,));ex('DELETE FROM layout_assets WHERE asset_id=%s',(i,));new=fullasset(i);audit('삭제','asset',i,new['asset_name'],snap(old),snap(new),reason=reason);return redirect('/assets')
  d=formdata();d['enabled']=1 if state=='use' else 0;cs=list(d);ex('UPDATE assets SET '+','.join(k+'=%s' for k in cs)+',deleted_at=NULL WHERE id=%s',[d[k] for k in cs]+[i]);save_specs(i);save_licenses(i);new=fullasset(i);audit('수정','asset',i,new['asset_name'],snap(old),snap(new));return redirect('/assets')
 return render_template('asset_form.html',asset=old,purposes=q('SELECT * FROM purposes WHERE enabled=1 OR id=%s',(old['purpose_id'],)),locations=q('SELECT * FROM locations WHERE enabled=1 ORDER BY display_order,name'),ev=erange(),specs=specs(i),licenses=licenses(i))
@app.get('/assets/export')
@login_req
def export_assets():
 rows=q('SELECT a.*,p.name purpose FROM assets a JOIN purposes p ON p.id=a.purpose_id WHERE a.deleted_at IS NULL ORDER BY a.id');wb=Workbook();ws=wb.active;ws.title='assets';headers=['자산번호','자산종류','구분','자산명','용도','사용자','장소','제조사','모델명','S/N','구입일','수량','MAC','OS','IP','PORT','월점검','C','I','A','R','사용상태','CPU','MEM','DISK','NIC','PSU','ETC'];ws.append(headers)
 for a in rows:
  sm={t:[] for t in ['CPU','MEM','DISK','NIC','PSU','ETC']}
  for x in specs(a['id']):sm[x['spec_type']].append(f"{x['model_name']}|{x['quantity']}")
  ws.append([a['asset_no'],'H/W' if a['asset_type']=='hardware' else 'S/W','시료' if a['asset_class']=='sample' else '일반',a['asset_name'],a['purpose'],a['assignee'],a['location'],a['manufacturer'],a['model_name'],a['serial_no'],a['purchase_date'],a['quantity'],a['mac_address'],a['os_name'],a['ip_address'],a['port_info'],a['monthly_check'],a['eval_c'],a['eval_i'],a['eval_a'],a['eval_r'],a['enabled']]+[';'.join(sm[t]) for t in ['CPU','MEM','DISK','NIC','PSU','ETC']])
 bio=BytesIO();wb.save(bio);bio.seek(0);return send_file(bio,download_name='naonworks_assets.xlsx',as_attachment=True)
@app.post('/assets/import')
@roles('admin')
def import_assets():
 f=request.files.get('file');
 if not f:flash('Excel 파일을 선택하세요.','danger');return redirect('/assets')
 wb=load_workbook(f,data_only=True);ws=wb.active;heads=[str(x.value or '').strip() for x in ws[1]];idx={h:i for i,h in enumerate(heads)};created=updated=errors=0
 for row in ws.iter_rows(min_row=2,values_only=True):
  try:
   g=lambda h: row[idx[h]] if h in idx else None;no=str(g('자산번호') or '').strip();name=str(g('자산명') or '').strip();pur=str(g('용도') or '').strip();user=str(g('사용자') or '').strip()
   if not no or not name or not pur or not user:raise ValueError('필수값')
   p=q('SELECT * FROM purposes WHERE name=%s',(pur,),True)
   if not p:raise ValueError('용도없음')
   typ='software' if str(g('자산종류')).upper() in ('S/W','SOFTWARE') else 'hardware';cl='sample' if str(g('구분'))=='시료' else 'normal';vals=(typ,cl,name,p['id'],user,g('장소'),g('제조사'),g('모델명'),g('S/N'),g('구입일'),int(g('수량') or 0) if typ=='software' else None,g('MAC'),g('OS'),g('IP'),g('PORT'),int(g('월점검') or 0),g('C'),g('I'),g('A'),g('R'),int(g('사용상태') if g('사용상태') is not None else 1))
   old=q('SELECT id FROM assets WHERE asset_no=%s',(no,),True)
   if old:aid=old['id'];ex('UPDATE assets SET asset_type=%s,asset_class=%s,asset_name=%s,purpose_id=%s,assignee=%s,location=%s,manufacturer=%s,model_name=%s,serial_no=%s,purchase_date=%s,quantity=%s,mac_address=%s,os_name=%s,ip_address=%s,port_info=%s,monthly_check=%s,eval_c=%s,eval_i=%s,eval_a=%s,eval_r=%s,enabled=%s,deleted_at=NULL WHERE id=%s',vals+(aid,));updated+=1
   else:aid=ex('INSERT INTO assets(asset_no,asset_type,asset_class,asset_name,purpose_id,assignee,location,manufacturer,model_name,serial_no,purchase_date,quantity,mac_address,os_name,ip_address,port_info,monthly_check,eval_c,eval_i,eval_a,eval_r,enabled) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(no,)+vals);created+=1
   ex('DELETE FROM sample_specs WHERE asset_id=%s',(aid,))
   if typ=='hardware':
    for t in ['CPU','MEM','DISK','NIC','PSU','ETC']:
     for item in str(g(t) or '').split(';'):
      if not item.strip():continue
      parts=item.rsplit('|',1);ex('INSERT INTO sample_specs(asset_id,spec_type,model_name,quantity) VALUES(%s,%s,%s,%s)',(aid,t,parts[0].strip(),int(parts[1]) if len(parts)>1 and parts[1].strip().isdigit() else 1))
  except Exception:errors+=1
 # sequence correction per purpose/prefix
 for p in q('SELECT * FROM purposes'):
  mx=0
  for a in q('SELECT asset_no FROM assets WHERE purpose_id=%s',(p['id'],)):
   m=re.match('^'+re.escape(p['asset_prefix'])+r'-(\d+)$',a['asset_no'])
   if m:mx=max(mx,int(m.group(1)))
  ex('UPDATE purposes SET next_sequence=%s WHERE id=%s',(mx+1,p['id']))
 flash(f'Import 완료: 신규 {created}, 업데이트 {updated}, 오류 {errors}','success');return redirect('/assets')
@app.get('/io')
@login_req
def io():
 sw=q("SELECT a.*,(SELECT COUNT(*) FROM software_licenses l WHERE l.asset_id=a.id AND l.enabled=1) registered_licenses,(SELECT COUNT(*) FROM software_license_assignments sa WHERE sa.asset_id=a.id AND sa.returned_date IS NULL) used_count,GREATEST(COALESCE(a.quantity,0)-(SELECT COUNT(*) FROM software_license_assignments sa WHERE sa.asset_id=a.id AND sa.returned_date IS NULL),0) available_capacity FROM assets a WHERE a.asset_type='software' AND a.deleted_at IS NULL ORDER BY a.asset_name")
 sm=q("SELECT a.*,p.name purpose FROM assets a JOIN purposes p ON p.id=a.purpose_id WHERE a.asset_type='hardware' AND a.asset_class='sample' AND a.deleted_at IS NULL ORDER BY a.asset_name")
 for a in sm:
  r=q("SELECT r.id request_id,r.status request_status,u.display_name AS requester_name FROM sample_requests r LEFT JOIN users u ON u.id=r.requester_user_id WHERE r.asset_id=%s AND r.status IN ('pending','approved','issued') ORDER BY r.id DESC LIMIT 1",(a['id'],),True);a['request_id']=r['request_id'] if r else None;a['request_status']=r['request_status'] if r else None;a['current_user']=r['requester_name'] if r else None;a['specs']=specs(a['id'])
 return render_template('io.html',sw=sw,samples=sm)
@app.get('/api/assets/<int:i>/info')
@login_req
def asset_info(i):
 a=fullasset(i) or abort(404);d={k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in a.items()};d['monthly_check_label']='대상' if a.get('monthly_check') else '비대상';d['specs']=specs(i) if a['asset_type']=='hardware' else []
 if a['asset_type']=='software':
  used=q('SELECT COUNT(*) n FROM software_license_assignments WHERE asset_id=%s AND returned_date IS NULL',(i,),True)['n'];d['license_total']=q('SELECT COUNT(*) n FROM software_licenses WHERE asset_id=%s AND enabled=1',(i,),True)['n'];d['remaining_quantity']=max(int(a.get('quantity') or 0)-used,0)
 return jsonify(d)
@app.get('/io/<int:i>/history')
@login_req
def ioh(i):
 ass=q("SELECT sa.*,l.license_code FROM software_license_assignments sa LEFT JOIN software_licenses l ON l.id=sa.license_id WHERE sa.asset_id=%s ORDER BY sa.id DESC",(i,))
 for x in ass:
  for k,v in list(x.items()):
   if hasattr(v,'isoformat'):x[k]=v.isoformat()
 a=fullasset(i);return jsonify(asset={'asset_no':a['asset_no'],'asset_name':a['asset_name']},assignments=ass)
@app.get('/software/<int:i>/available')
@roles('admin','oper')
def sw_available_direct(i):
 a=fullasset(i) or abort(404);ls=q("SELECT l.id,l.license_code FROM software_licenses l WHERE l.asset_id=%s AND l.enabled=1 AND NOT EXISTS(SELECT 1 FROM software_license_assignments sa WHERE sa.license_id=l.id AND sa.returned_date IS NULL) ORDER BY l.id",(i,));used=q('SELECT COUNT(*) n FROM software_license_assignments WHERE asset_id=%s AND returned_date IS NULL',(i,),True)['n'];return jsonify(asset={'id':i,'asset_no':a['asset_no'],'asset_name':a['asset_name'],'quantity':a['quantity'] or 0,'remaining':max(int(a['quantity'] or 0)-used,0)},licenses=ls)
@app.post('/software/<int:i>/issue')
@roles('admin','oper')
def sw_issue_direct(i):
 a=fullasset(i) or abort(404);user=request.form.get('user_name','').strip();ids=[int(x) for x in request.form.getlist('license_ids')];qty=int(request.form.get('quantity') or 0)
 if not user:abort(400)
 used=q('SELECT COUNT(*) n FROM software_license_assignments WHERE asset_id=%s AND returned_date IS NULL',(i,),True)['n']
 if ids:
  if used+len(ids)>int(a['quantity'] or 0):abort(400)
  for lid in ids:
   ok=q("SELECT id FROM software_licenses WHERE id=%s AND asset_id=%s AND enabled=1 AND NOT EXISTS(SELECT 1 FROM software_license_assignments WHERE license_id=%s AND returned_date IS NULL)",(lid,i,lid),True)
   if not ok:abort(400)
   ex('INSERT INTO software_license_assignments(asset_id,license_id,user_name,assigned_date,actor_user_id) VALUES(%s,%s,%s,CURDATE(),%s)',(i,lid,user,request.user['id']))
 else:
  if qty<1 or used+qty>int(a['quantity'] or 0):abort(400)
  for _ in range(qty):ex('INSERT INTO software_license_assignments(asset_id,license_id,user_name,assigned_date,actor_user_id) VALUES(%s,NULL,%s,CURDATE(),%s)',(i,user,request.user['id']))
 audit('S/W 지급','software_assignment',i,a['asset_name'],a={'user':user,'quantity':len(ids) if ids else qty},no=a['asset_no']);return redirect('/io')
@app.post('/software-assignment/<int:i>/return')
@roles('admin','oper')
def sw_return(i):
 a=q("SELECT sa.*,x.asset_no,x.asset_name FROM software_license_assignments sa JOIN assets x ON x.id=sa.asset_id WHERE sa.id=%s",(i,),True) or abort(404);ex('UPDATE software_license_assignments SET returned_date=CURDATE() WHERE id=%s AND returned_date IS NULL',(i,));audit('S/W 회수','software_assignment',i,a['asset_name'],no=a['asset_no']);return redirect('/io')
@app.get('/samples/<int:i>/history')
@login_req
def sample_history(i):
 a=fullasset(i) or abort(404);rows=q("SELECT r.*,u.display_name requester,ap.display_name approver FROM sample_requests r JOIN users u ON u.id=r.requester_user_id LEFT JOIN users ap ON ap.id=r.approver_user_id WHERE r.asset_id=%s ORDER BY r.id DESC",(i,))
 for x in rows:
  for k,v in list(x.items()):
   if hasattr(v,'isoformat'):x[k]=v.isoformat()
 return jsonify(asset={'asset_no':a['asset_no'],'asset_name':a['asset_name']},history=rows)
@app.post('/samples/<int:i>/request')
@login_req
def sample_request(i):
 a=fullasset(i) or abort(404)
 if a['asset_class']!='sample' or q("SELECT id FROM sample_requests WHERE asset_id=%s AND status IN ('pending','approved','issued')",(i,),True):abort(400)
 rid=ex("INSERT INTO sample_requests(asset_id,requester_user_id,purpose_text,start_date,due_date,memo) VALUES(%s,%s,%s,%s,%s,%s)",(i,request.user['id'],request.form['purpose_text'],request.form['start_date'],request.form['due_date'],request.form.get('memo')));audit('시료 신청','sample_request',rid,a['asset_name'],a={'status':'승인대기'},no=a['asset_no']);return redirect('/io')
@app.post('/sample-requests/<int:i>/<action>')
@roles('admin','oper')
def sample_action(i,action):
 r=q('SELECT r.*,a.asset_no,a.asset_name FROM sample_requests r JOIN assets a ON a.id=r.asset_id WHERE r.id=%s',(i,),True) or abort(404)
 if action=='approve' and r['status']=='pending':ex("UPDATE sample_requests SET status='approved',approver_user_id=%s,approved_at=NOW() WHERE id=%s",(request.user['id'],i));act='승인'
 elif action=='reject' and r['status']=='pending':ex("UPDATE sample_requests SET status='rejected',approver_user_id=%s,approved_at=NOW(),reject_reason=%s WHERE id=%s",(request.user['id'],request.form.get('reason'),i));act='반려'
 elif action=='issue' and r['status']=='approved':ex("UPDATE sample_requests SET status='issued',issued_at=NOW() WHERE id=%s",(i,));ex('DELETE FROM layout_assets WHERE asset_id=%s',(r['asset_id'],));act='불출'
 elif action=='return' and r['status']=='issued':ex("UPDATE sample_requests SET status='returned',returned_at=NOW() WHERE id=%s",(i,));act='반납'
 else:abort(400)
 audit('시료 '+act,'sample_request',i,r['asset_name'],b={'status':r['status']},a={'status':act},reason=request.form.get('reason'),no=r['asset_no']);return redirect('/io')
@app.get('/history')
@login_req
def history():return render_template('history.html',rows=q('SELECT l.*,u.display_name FROM audit_logs l LEFT JOIN users u ON u.id=l.actor_user_id ORDER BY l.id DESC LIMIT 1000'))
@app.get('/rules')
@roles('admin')
def rules():d={x['key']:int(x['value']) for x in q('SELECT * FROM settings')};return render_template('rules.html',purposes=q('SELECT * FROM purposes ORDER BY id'),locations=q('SELECT * FROM locations ORDER BY display_order,name'),mn=d['eval_min'],mx=d['eval_max'])
@app.post('/purposes')
@roles('admin')
def padd():ex('INSERT INTO purposes(name,asset_prefix,server_target) VALUES(%s,%s,%s)',(request.form['name'].strip(),request.form['asset_prefix'].strip().upper(),1 if request.form.get('server_target') else 0));return redirect('/rules')
@app.post('/locations')
@roles('admin')
def location_add():
 name=request.form.get('name','').strip()
 if name:ex('INSERT INTO locations(name,display_order) VALUES(%s,(SELECT COALESCE(MAX(z.display_order),0)+1 FROM locations z))',(name,))
 return redirect('/rules')
@app.post('/locations/<int:i>')
@roles('admin')
def location_edit(i):ex('UPDATE locations SET name=%s,enabled=%s WHERE id=%s',(request.form['name'].strip(),1 if request.form.get('enabled') else 0,i));return redirect('/rules')
@app.post('/rules')
@roles('admin')
def rulesapply():
 ids=[int(x) for x in request.form.getlist('purpose_id') if x];prefs=[request.form[f'prefix_{i}'].strip().upper() for i in ids]
 if len(prefs)!=len(set(prefs)):flash('자산번호 규칙은 중복될 수 없습니다.','danger');return redirect('/rules')
 ex("UPDATE settings SET value=CASE `key` WHEN 'eval_min' THEN %s ELSE %s END",(int(request.form['eval_min']),int(request.form['eval_max'])))
 for i in ids:ex('UPDATE purposes SET name=%s,asset_prefix=%s,server_target=%s,enabled=%s WHERE id=%s',(request.form[f'name_{i}'].strip(),request.form[f'prefix_{i}'].strip().upper(),1 if request.form.get(f'server_{i}') else 0,1 if request.form.get(f'enabled_{i}') else 0,i))
 return redirect('/rules')
@app.route('/users',methods=['GET','POST'])
@roles('admin','oper')
def users():
 if request.method=='POST':
  role=request.form['role'];
  if request.user['role']=='oper' and role!='user':abort(403)
  ex('INSERT INTO users(username,password_hash,display_name,role) VALUES(%s,%s,%s,%s)',(request.form['username'],generate_password_hash(request.form['password']),request.form['display_name'],role));return redirect('/users')
 return render_template('users.html',rows=q("SELECT *,CASE WHEN enabled=1 AND last_seen_at>=NOW()-INTERVAL 5 MINUTE AND (last_logout_at IS NULL OR last_logout_at<last_seen_at) THEN 1 ELSE 0 END connected FROM users ORDER BY id"))
@app.post('/users/<int:i>')
@roles('admin')
def uedit(i):
 current=q('SELECT role,enabled FROM users WHERE id=%s',(i,),True)
 if i==request.user['id'] and (request.form['role']!=current['role'] or int(request.form['enabled'])!=int(current['enabled'])):flash('자기 자신의 권한/상태는 변경할 수 없습니다.','danger');return redirect('/users')
 ex('UPDATE users SET role=%s,display_name=%s,enabled=%s WHERE id=%s',(request.form['role'],request.form['display_name'],int(request.form['enabled']),i));return redirect('/users')
@app.get('/servers')
@login_req
def servers():return render_template('servers.html',layouts=q('SELECT * FROM layouts ORDER BY display_order,id'),assets=q("SELECT a.*,p.name purpose FROM assets a JOIN purposes p ON p.id=a.purpose_id WHERE a.asset_type='hardware' AND p.server_target=1 AND a.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM sample_requests sr WHERE sr.asset_id=a.id AND sr.status='issued')"),placed=q('SELECT la.*,a.asset_no,a.asset_name,a.enabled,a.monthly_check,a.ip_address,a.manufacturer,a.model_name,a.serial_no,a.os_name,a.port_info,a.assignee,a.location,p.name purpose FROM layout_assets la JOIN assets a ON a.id=la.asset_id JOIN purposes p ON p.id=a.purpose_id'))
@app.post('/layouts')
@roles('admin')
def lnew():
 n=q('SELECT COALESCE(MAX(display_order),0)+1 n FROM layouts',one=True)['n'];ex('INSERT INTO layouts(kind,name,description,display_order) VALUES(%s,%s,%s,%s)',(request.form['kind'],request.form['name'],request.form.get('description'),n));return redirect('/servers')
@app.post('/layouts/<int:i>/delete')
@roles('admin')
def ldel(i):ex('DELETE FROM layouts WHERE id=%s',(i,));return redirect('/servers')
@app.post('/layouts/<int:i>/assets')
@roles('admin','oper')
def ladd(i):
 for aid in request.form.getlist('asset_ids'):ex('INSERT INTO layout_assets(layout_id,asset_id) VALUES(%s,%s) ON DUPLICATE KEY UPDATE layout_id=VALUES(layout_id)',(i,int(aid)))
 return redirect('/servers')
@app.post('/layouts/<int:i>/assets/remove')
@roles('admin','oper')
def lremove(i):
 for aid in request.form.getlist('asset_ids'):ex('DELETE FROM layout_assets WHERE layout_id=%s AND asset_id=%s',(i,int(aid)))
 return redirect('/servers')
@app.post('/api/asset-move')
@roles('admin','oper')
def amove():d=request.json;ex('INSERT INTO layout_assets(layout_id,asset_id) VALUES(%s,%s) ON DUPLICATE KEY UPDATE layout_id=VALUES(layout_id)',(int(d['layout_id']),int(d['asset_id'])));return jsonify(ok=True)
@app.post('/api/layout-order')
@roles('admin','oper')
def lorder():
 for n,i in enumerate(request.json['ids']):ex('UPDATE layouts SET display_order=%s WHERE id=%s',(n,int(i)))
 return jsonify(ok=True)
