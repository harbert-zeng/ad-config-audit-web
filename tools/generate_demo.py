"""Build fictional fixtures from scratch; never reads an account export."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STAMP = '2026-01-01T00:00:00Z'
d = dict(schema='ad-config-demo-v1', demo=True, snapshot_id='DEMO-SNAPSHOT-001', captured_at=STAMP, settings_read_at=STAMP,
 account_id='DEMO-ACCOUNT', account='Demo 广告账户（虚构）', project='Demo', timezone='Europe/Berlin', currency='USD',
 counts=dict(campaigns=2, adsets=2, ads=4, creatives=4),
 scope_summary=dict(checked_at=STAMP, checked_ads=4, included=4, excluded=0, excluded_by_reason={}, policy='synthetic_fixture'),
 excluded_ads=[], status_conflicts=dict(unresolved=False,campaigns=[],reason='',reported_at=STAMP),
 campaigns=[],adsets=[],ads=[],features=[],material_groups=[],landing_groups=[],landing_source=STAMP,
 coverage=dict(urls=4,body=4,media_and_copy=0,images=0,identity=True,utm=False,all_enhancements=False,visual_content_checked=False),
 rule_version='demo-v1',source_note='全部为程序创建的虚构示例，不来自任何真实账户。')
identity = dict(checked_at=STAMP,groups=[],account_available_pages=[],facebook_post_owner_count=4,facebook_named_count=4,
 instagram_media_count=0,instagram_identity_count=4,partnership_verified_count=0,basis='SYNTHETIC',limitations=['虚构数据，不能用于业务判断'],
 instagram_named_count=4,instagram_accounts=[],instagram_checked_at=STAMP,instagram_source='SYNTHETIC')
for country in ['DE','FR']:
 lower=country.lower();cid=f'DEMO-CAMPAIGN-{country}';sid=f'DEMO-ADSET-{country}';pid=f'DEMO-PAGE-{country}';iid=f'DEMO-IG-{country}'
 cname=f'{lower}_demo_product_launch';sname=f'{country}_Demo_Audience';url=f'https://example.com/eu-{lower}/products/demo-product'
 ids=[f'DEMO-AD-{country}-{i}' for i in [1,2]]
 delivery={'status':'active','substatuses':[]}
 d['campaigns'].append(dict(id=cid,name=cname,status='ACTIVE',effective_status='ACTIVE',daily_budget={'value':'100','unit':'USD'},start_time=STAMP,bid_strategy='LOWEST_COST_WITHOUT_CAP',delivery=delivery,short=country,adset_count=1,ad_count=2,countries=[country]))
 d['adsets'].append(dict(id=sid,name=sname,campaign_id=cid,campaign_name=cname,status='ACTIVE',effective_status='ACTIVE',start_time=STAMP,optimization_goal='OFFSITE_CONVERSIONS',attribution_spec=[{'event_type':'CLICK_THROUGH','window_days':7}],delivery=delivery,targeting={'age_min':18,'age_max':65,'geo_locations':{'countries':[country]},'publisher_platforms':['facebook','instagram']}))
 for i,aid in enumerate(ids,1):
  d['ads'].append(dict(id=aid,name=f'{country}_Demo_Ad_{i}',adset_id=sid,campaign_id=cid,creative_id=f'DEMO-CREATIVE-{country}-{i}',adset_name=sname,campaign_name=cname,status='ACTIVE',effective_status='ACTIVE',delivery=delivery,scope_status='ACTIVE',scope_reason='虚构示例：三层开启',status_checked_at=STAMP,countries=[country],body='Early Black Friday' if i==1 else 'Last chance',title='Demo product',description='Fictional example',cta='LEARN_MORE',url=url,image_hash=None,video_id=None,image='',image_is_video_cover=False,features=[],feature_values=None,feature_states={},media_evidence='SYNTHETIC',identity=dict(facebook_page_id=pid,facebook_page_name=f'Demo {country}',facebook_evidence='SYNTHETIC',effective_object_story_id=None,instagram_media_id=None,instagram_account_id=iid,instagram_username=f'demo_{lower}',instagram_name=f'Demo {country}',instagram_evidence='SYNTHETIC',instagram_name_evidence='SYNTHETIC',partnership_status='UNKNOWN',checked_at=STAMP,instagram_checked_at=STAMP),landing_urls=[url],landing_evidence=[{'field':'SYNTHETIC','url':url}],landing_checked_at=STAMP))
 identity['account_available_pages'].append({'page_id':pid,'page_name':f'Demo {country}'})
 ig={'account_id':iid,'username':f'demo_{lower}','name':f'Demo {country}','count':2,'share':1.0,'ad_ids':ids}
 identity['instagram_accounts'].append({**ig,'name_evidence':'SYNTHETIC','verified_ad_id':ids[0]})
 identity['groups'].append(dict(country=country,ad_ids=ids,total=2,known=2,pages=[{'page_id':pid,'name':f'Demo {country}','count':2,'share':1.0,'ad_ids':ids}],recommended_page_id=pid,confirmed=False,exception_count=0,instagram_accounts=[ig],instagram_known=2,recommended_instagram_id=iid))
 d['landing_groups'].append(dict(key=f'DEMO-LANDING-{country}',urls=[url],count=2,ad_ids=ids,campaign_names=[cname],adset_names=[sname],suggested_rules=[{'field':'campaign','op':'contains','value':f'{lower}_demo_','second':False,'field2':'adset','op2':'contains','value2':'','confirmed':False,'url':url,'matched_count':2}],uncovered_suggestion_count=0))
d['identity_summary']=identity
(ROOT/'dist/data.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
print('Generated fictional snapshot: 2 campaigns, 4 ads.')
