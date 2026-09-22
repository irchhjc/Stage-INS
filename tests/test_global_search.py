from app.extensions import db
from app.models import DSF, ImportSession, User


def seed():
    users=[User(username='alpha',role='controller'),User(username='beta',role='controller',is_active=False)]
    for u in users: u.set_password('motdepasse-test')
    sessions=[ImportSession(filename='ancien.xlsx',filepath='test',sheet_name='S'),ImportSession(filename='nouveau.xlsx',filepath='test',sheet_name='S')]
    db.session.add_all(users+sessions);db.session.flush()
    rows=[DSF(import_session_id=sessions[0].id,row_index=2,raison_sociale='GLOBALE Un',niu='ABC101',assignee=users[0]),DSF(import_session_id=sessions[1].id,row_index=2,raison_sociale='GLOBALE Deux',numero_dsf='REF202',assignee=users[1]),DSF(import_session_id=sessions[0].id,row_index=3,raison_sociale='GLOBALE Trois',sigle='SIG303')]
    db.session.add_all(rows);db.session.commit()
    return users,sessions,rows


def test_search_across_workbooks_and_assignments(client):
    _,sessions,rows=seed()
    r=client.get('/admin/search?q=globale&session_id='+str(sessions[1].id))
    assert r.status_code == 200
    html=r.get_data(as_text=True)
    assert all(f'data-dsf-id="{d.id}"' in html for d in rows)
    for query,index in [('ABC101',0),('REF202',1),('SIG303',2),('beta',1)]:
        html=client.get('/admin/search',query_string={'q':query}).get_data(as_text=True)
        assert f'data-dsf-id="{rows[index].id}"' in html
        assert sum(f'data-dsf-id="{d.id}"' in html for d in rows)==1
    html=client.get('/admin/search?q=ancien.xlsx').get_data(as_text=True)
    assert f'data-dsf-id="{rows[0].id}"' in html and f'data-dsf-id="{rows[2].id}"' in html
    html=client.get('/admin/search?assignment=unassigned').get_data(as_text=True)
    assert f'data-dsf-id="{rows[2].id}"' in html and f'data-dsf-id="{rows[0].id}"' not in html
    html=client.get('/admin/search?assignment=assigned').get_data(as_text=True)
    assert f'data-dsf-id="{rows[2].id}"' not in html


def test_admin_only_and_literal_search(client):
    users,_,_=seed()
    assert 'Aucune DSF' in client.get('/admin/search?q=%25').get_data(as_text=True)
    with client.session_transaction() as s:s['user_id']=users[0].id
    assert client.get('/admin/search').status_code == 403


def test_pagination_preserves_filters(client):
    users,sessions,_=seed()
    db.session.add_all([DSF(import_session_id=sessions[0].id,row_index=i+10,raison_sociale='PAGE '+str(i),assignee=users[0]) for i in range(55)])
    db.session.commit()
    html=client.get('/admin/search?q=PAGE&assignment=assigned').get_data(as_text=True)
    assert html.count('data-dsf-id=') == 50
    assert 'q=PAGE' in html and 'assignment=assigned' in html and 'page=2' in html
    html=client.get('/admin/search?q=PAGE&assignment=assigned&page=2').get_data(as_text=True)
    assert html.count('data-dsf-id=') == 5
