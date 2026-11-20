"""Business destination matching only. No HTTP, redirect or security checks."""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from collections import defaultdict
import hashlib,json

TRACKING={'fbclid','gclid','dclid','msclkid','ttclid','_gl','mc_cid','mc_eid'}
def canonical_url(value):
    try:
        u=urlsplit(value.strip())
        if u.scheme.lower() not in ('http','https') or not u.hostname or u.username or u.password:return None
        host=u.hostname.lower()
        port=u.port
        if port and (u.scheme.lower(),port) not in [('https',443),('http',80)]:host+=':'+str(port)
        query=sorted((k,v) for k,v in parse_qsl(u.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in TRACKING)
        return urlunsplit((u.scheme.lower(),host,u.path.rstrip('/') or '/',urlencode(query),u.fragment))
    except (ValueError,AttributeError):return None

def expected_urls(rule):
    return {canonical_url(v) for v in rule.get('url','').splitlines() if v.strip()}

def matches(ad,rule):
    def one(suffix=''):
        field={'campaign':'campaign_name','adset':'adset_name','ad':'name'}.get(rule.get('field'+suffix))
        value=rule.get('value'+suffix,'').strip().lower()
        if not field or not value:return False
        name=ad.get(field,'').lower();op=rule.get('op'+suffix,'contains')
        if op=='equals':return name==value
        if op=='not_equals':return name!=value
        if op=='not_contains':return value not in name
        return op=='contains' and value in name
    return one() and (not rule.get('second') or one('2'))

def actual_urls(ad):
    return {canonical_url(u) for u in ad.get('landing_urls',[]) if u}

def check_rules(ads,rules):
    result=[]
    for ad in ads:
        matched=[r for r in rules if matches(ad,r)]
        status='MISSING_RULE';allowed=set();actual=actual_urls(ad)
        if matched:
            if any(not r.get('confirmed') for r in matched):status='UNCONFIRMED_RULE'
            else:
                sets=[expected_urls(r) for r in matched]
                if any(not s or None in s for s in sets):status='INVALID_RULE'
                elif len({tuple(sorted(s)) for s in sets})>1:status='RULE_CONFLICT'
                else:
                    allowed=sets[0]
                    if not actual or None in actual:status='UNREADABLE'
                    elif actual<=allowed:status='MATCH'
                    else:status='URL_MISMATCH'
        result.append({'ad_id':ad['id'],'status':status,'actual_urls':sorted(u for u in actual if u),'allowed_urls':sorted(allowed)})
    return result

def compare_inherited(ads,baseline):
    result=[]
    for a in ads:
        actual=actual_urls(a);old=baseline.get(a['id'])
        status='UNREADABLE' if not actual or None in actual else 'NEW_AD' if old is None else 'MATCH' if actual=={canonical_url(u) for u in old} else 'URL_CHANGED'
        result.append({'ad_id':a['id'],'status':status})
    return result

def enrich_landing(ads,evidence):
    records={r['ad_id']:r for r in evidence['ads']}
    groups=defaultdict(list)
    for a in ads:
        row=records.get(a['id'])
        if row:
            a['landing_urls']=[v['url'] for v in row['destinations']]
            a['landing_evidence']=row['destinations']
            a['landing_checked_at']=evidence['captured_at']
            a['url']=a['landing_urls'][0] if a['landing_urls'] else None
        else:a['landing_urls']=[a['url']] if a.get('url') else []
        urls=actual_urls(a)
        if urls and None not in urls:groups[tuple(sorted(urls))].append(a)
    # Candidate name rules are checked against every ad. Only zero-mismatch
    # candidates are suggested; these are observations, never approvals.
    prefixes={('_'.join(a['campaign_name'].split('_')[:i])+'_') for a in ads for i in range(1,len(a['campaign_name'].split('_')))}
    candidates=[]
    for field,op,value in [('campaign','contains',v) for v in sorted(prefixes)]+[('campaign','equals',v) for v in sorted({a['campaign_name'] for a in ads})]:
        base={'field':field,'op':op,'value':value,'second':False,'field2':'adset','op2':'equals','value2':'','confirmed':False}
        members=[a for a in ads if matches(a,base)]
        if not members:continue
        variants=[base]
        if len({tuple(sorted(actual_urls(a),key=lambda x:x or '')) for a in members})>1:
            variants += [{**base,'second':True,'op2':op2,'value2':name} for name in sorted({a['adset_name'] for a in members}) for op2 in ['equals','not_equals']]
        for r in variants:
            members2=[a for a in members if matches(a,r)]
            destinations={tuple(sorted(actual_urls(a),key=lambda x:x or '')) for a in members2}
            if len(destinations)==1 and members2:
                urls=next(iter(destinations))
                if urls and None not in urls:candidates.append((urls,{a['id'] for a in members2},r))
    result=[]
    for urls,members in sorted(groups.items()):
        remaining={a['id'] for a in members};rules=[]
        while remaining:
            options=[(ids & remaining,r) for dest,ids,r in candidates if dest==urls and ids & remaining]
            if not options:break
            covered,r=min(options,key=lambda item:(-len(item[0]),int(item[1]['second']),len(item[1]['value'])+len(item[1]['value2']),json.dumps(item[1],sort_keys=True)))
            rules.append({**r,'url':'\n'.join(urls),'matched_count':len(covered)})
            remaining-=covered
        result.append({'key':hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:16],
                       'urls':list(urls),'count':len(members),'ad_ids':[a['id'] for a in members],
                       'campaign_names':sorted({a['campaign_name'] for a in members}),
                       'adset_names':sorted({a['adset_name'] for a in members}),
                       'suggested_rules':rules,'uncovered_suggestion_count':len(remaining)})
    return result
