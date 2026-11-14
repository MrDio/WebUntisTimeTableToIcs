import os, json, urllib.request, urllib.parse, datetime, hashlib, pathlib, sys
from zoneinfo import ZoneInfo

BASE = os.getenv('BASE_URL', 'moerike-gym-esslingen.webuntis.com').replace('https://','').strip('/')
STUDENT = os.getenv('ELEMENT_ID','5028')
TENANT = os.getenv('TENANT_ID','4203400')
COOKIE = os.getenv('WEBUNTIS_COOKIE', '').strip()
TZ = ZoneInfo('Europe/Berlin')

def esc(s):
    return str(s or '').replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')

def fields(items):
    return [p['current'] for p in (items or []) if p.get('current')]

def make_event(uid,start,end,summary,desc='',location='',all_day=False,status='CONFIRMED'):
    now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VEVENT',f'UID:{uid}@webuntis-local',f'DTSTAMP:{now}']
    if all_day:
        lines += [f'DTSTART;VALUE=DATE:{start}',f'DTEND;VALUE=DATE:{end}']
    else:
        lines += [f'DTSTART;TZID=Europe/Berlin:{start}',f'DTEND;TZID=Europe/Berlin:{end}']
    lines += [f'SUMMARY:{esc(summary)}',f'DESCRIPTION:{esc(desc)}',f'LOCATION:{esc(location)}',f'STATUS:{status}','END:VEVENT']
    return lines


def fetch(start, end):
    import urllib.error

    params = urllib.parse.urlencode({
        'start': start.isoformat(),
        'end': end.isoformat(),
        'format': 6,
        'resourceType': 'STUDENT',
        'resources': STUDENT,
        'periodTypes': '',
        'timetableType': 'MY_TIMETABLE',
        'layout': 'START_TIME'
    })

    url = f'https://{BASE}/WebUntis/api/rest/view/v1/timetable/entries?{params}'

    headers = {
        'Accept': 'application/json',
        'Tenant-Id': TENANT,
        'X-Webuntis-Api-School-Year-Id': os.getenv('SCHOOL_YEAR_ID', '22'),
        'User-Agent': 'Mozilla/5.0',
        'Referer': f'https://{BASE}/timetable/my-student'
    }

    if COOKIE:
        headers['Cookie'] = COOKIE

    print("API path: /WebUntis/api/rest/view/v1/timetable/entries")
    print("Requested dates:", start, end)
    print("Cookie configured:", bool(COOKIE))
    print("Tenant configured:", bool(TENANT))
    print("School year:", headers['X-Webuntis-Api-School-Year-Id'])

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            print("HTTP status:", response.status)
            return json.load(response)

    except urllib.error.HTTPError as e:
        print("HTTP status:", e.code)
        print("Response content type:", e.headers.get('Content-Type'))
        print("Response body:", e.read(1000).decode('utf-8', errors='replace'))
        raise RuntimeError(f"WebUntis API returned HTTP {e.code}") from None


def main():
    today=datetime.datetime.now(TZ).date()
    monday=today-datetime.timedelta(days=today.weekday())+datetime.timedelta(days=7)
    events=[]; unavailable=[]; total=0
    # Request short ranges to respect server timetable limits.
    for w in range(1):
        start=monday+datetime.timedelta(weeks=w)
        end=start+datetime.timedelta(days=4)
        payload=fetch(start,end)
        if payload.get('errors'): raise RuntimeError(f'API returned errors: {payload["errors"]}')
        for day in payload.get('days',[]):
            if day.get('status')=='NOT_ALLOWED':
                unavailable.append(day['date']);continue
            for entry in day.get('gridEntries',[]):
                duration=entry.get('duration') or {}
                if not duration.get('start') or not duration.get('end'):continue
                subj=fields(entry.get('position1'))
                teachers=fields(entry.get('position2'))
                rooms=fields(entry.get('position3'))
                title=', '.join(x.get('longName') or x.get('shortName','') for x in subj) or entry.get('name') or 'Unterricht'
                if entry.get('type')=='EXAM': title='Klassenarbeit: '+title
                if entry.get('status')=='CANCELLED':title='Entfällt: '+title
                elif entry.get('status')=='CHANGED':title='Änderung: '+title
                teacher=', '.join(x.get('longName','') for x in teachers)
                room=', '.join(x.get('shortName','') for x in rooms)
                desc='Lehrkraft: '+teacher if teacher else ''
                for key in ('substitutionText','lessonText','lessonInfo'):
                    value=entry.get(key)
                    if value and value!='x':desc+='\n'+str(value)
                key='-'.join(map(str,entry.get('ids',[]))) or hashlib.sha256((duration['start']+title).encode()).hexdigest()[:16]
                uid=hashlib.sha256((STUDENT+'-'+key+'-'+duration['start']).encode()).hexdigest()[:24]
                events.extend(make_event(uid,duration['start'].replace('-','').replace(':',''),duration['end'].replace('-','').replace(':',''),title,desc,room,status='CANCELLED' if entry.get('status')=='CANCELLED' else 'CONFIRMED'))
                total+=1
            for entry in day.get('dayEntries',[]):
                duration=entry.get('duration') or {}
                if not entry.get('isFullDay') or not duration.get('start'):continue
                title=(entry.get('position1') or {}).get('longName') or entry.get('name') or 'Schultermin'
                date=datetime.date.fromisoformat(duration['start'][:10]); end=date+datetime.timedelta(days=1)
                events.extend(make_event('day-'+str(entry.get('id'))+'-'+date.isoformat(),date.strftime('%Y%m%d'),end.strftime('%Y%m%d'),title,all_day=True))
                total+=1
    if not total:raise RuntimeError('No events received. Refusing to overwrite calendar.')
    output=pathlib.Path('public/calendar.ics');output.parent.mkdir(exist_ok=True)
    output.write_text('\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//WebUntis to Daely//DE','CALSCALE:GREGORIAN','X-WR-CALNAME:Schulstundenplan','X-WR-TIMEZONE:Europe/Berlin','BEGIN:VTIMEZONE','TZID:Europe/Berlin','X-LIC-LOCATION:Europe/Berlin','BEGIN:DAYLIGHT','TZOFFSETFROM:+0100','TZOFFSETTO:+0200','TZNAME:CEST','DTSTART:19700329T020000','RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU','END:DAYLIGHT','BEGIN:STANDARD','TZOFFSETFROM:+0200','TZOFFSETTO:+0100','TZNAME:CET','DTSTART:19701025T030000','RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU','END:STANDARD','END:VTIMEZONE',*events,'END:VCALENDAR','']),encoding='utf-8')
    print(f'Created {output} with {total} events; unavailable dates: {len(unavailable)}')
if __name__=='__main__':main()
