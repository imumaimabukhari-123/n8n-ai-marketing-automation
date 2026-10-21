"""Builds workflow 2 (daily AI marketing report) and pushes it to the local n8n."""
import json, sys, urllib.request

API = "http://localhost:5678/api/v1"
KEY = open(sys.argv[1]).read().strip()
GEMINI_CRED = sys.argv[2]
LEADS_TABLE = sys.argv[3]
BREVO_CRED = sys.argv[4]
WORKFLOW_ID = sys.argv[5] if len(sys.argv) > 5 else None
OWNER = {"name": "Umaima", "email": "imumaimabukhari@gmail.com"}

STATS = r"""
// Work out the numbers for the last 7 days and build the Gemini request
const DAYS = 7;
const since = Date.now() - DAYS * 24 * 60 * 60 * 1000;
const leads = $input.all().map(i => i.json)
  .filter(l => new Date(l.createdAt).getTime() >= since);

const count = (key) => leads.reduce((acc, l) => {
  const k = l[key] || 'Not given';
  acc[k] = (acc[k] || 0) + 1;
  return acc;
}, {});

const stats = {
  period: `last ${DAYS} days`,
  total_leads: leads.length,
  by_temperature: count('temperature'),
  by_service: count('service'),
  by_budget: count('budget'),
  average_score: leads.length ? Math.round(leads.reduce((s, l) => s + (l.score || 0), 0) / leads.length) : 0,
  follow_ups_sent: leads.filter(l => l.email_sent).length,
  top_leads: [...leads].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 3)
    .map(l => ({ name: l.name, company: l.company, score: l.score, service: l.service, summary: l.summary })),
};

const prompt = `You are a marketing analyst for Syeda Umaima, a freelance software engineer
(Shopify stores, AI chatbots, n8n automations, Chrome extensions, MERN web apps).

Here are her lead numbers for the ${stats.period}:
${JSON.stringify(stats, null, 2)}

Write a short, practical report for her:
- headline: one sentence on how the week went
- insights: 3 short bullet points about what the numbers show (which services are in demand, lead quality, budgets)
- actions: 3 concrete things she should do this week (e.g. who to call first, what to post about, which gig to promote)
Be specific and use the numbers. Simple English.`;

const gemini_body = {
  contents: [{ parts: [{ text: prompt }] }],
  generationConfig: {
    responseMimeType: 'application/json',
    responseSchema: {
      type: 'OBJECT',
      properties: {
        headline: { type: 'STRING' },
        insights: { type: 'ARRAY', items: { type: 'STRING' } },
        actions: { type: 'ARRAY', items: { type: 'STRING' } },
      },
      required: ['headline', 'insights', 'actions'],
    },
  },
};

return [{ json: { stats, gemini_body } }];
"""

EMAIL = r"""
// Turn the numbers + AI analysis into a clean HTML email
const { stats } = $('Calculate weekly numbers').first().json;
const text = $input.first().json.candidates?.[0]?.content?.parts?.[0]?.text || '{}';
const ai = JSON.parse(text);

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const list = (items) => '<ul>' + items.map(i => `<li style="margin-bottom:6px">${esc(i)}</li>`).join('') + '</ul>';
const t = stats.by_temperature;
const tile = (label, value, color) =>
  `<td style="padding:12px;background:#f4f6fb;border-radius:8px;text-align:center">
     <div style="font-size:24px;font-weight:700;color:${color}">${value}</div>
     <div style="font-size:12px;color:#555">${label}</div></td>`;
const rows = (obj) => Object.entries(obj).sort((a, b) => b[1] - a[1])
  .map(([k, v]) => `<tr><td style="padding:4px 12px 4px 0">${esc(k)}</td><td><b>${v}</b></td></tr>`).join('');

const html = `
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:620px;margin:auto;color:#222">
  <h2 style="margin-bottom:4px">📊 Your marketing report</h2>
  <div style="color:#666;margin-bottom:16px">Leads from the ${esc(stats.period)}</div>
  <p style="font-size:16px"><b>${esc(ai.headline)}</b></p>
  <table cellspacing="8" style="width:100%"><tr>
    ${tile('New leads', stats.total_leads, '#3b5bdb')}
    ${tile('Hot', t.hot || 0, '#e03131')}
    ${tile('Warm', t.warm || 0, '#f08c00')}
    ${tile('Cold', t.cold || 0, '#868e96')}
    ${tile('Avg score', stats.average_score, '#2f9e44')}
  </tr></table>
  <h3>What the numbers show</h3>${list(ai.insights || [])}
  <h3>What to do this week</h3>${list(ai.actions || [])}
  <h3>Top leads</h3>
  <ol>${stats.top_leads.map(l => `<li><b>${esc(l.name)}</b>${l.company ? ' (' + esc(l.company) + ')' : ''}, ${l.score}/100, ${esc(l.service)}<br><span style="color:#555">${esc(l.summary)}</span></li>`).join('')}</ol>
  <h3>Services requested</h3><table>${rows(stats.by_service)}</table>
  <h3>Budgets</h3><table>${rows(stats.by_budget)}</table>
  <p style="color:#999;font-size:12px;margin-top:24px">Sent automatically by your n8n workflow. Follow-up emails sent: ${stats.follow_ups_sent}.</p>
</div>`;

return [{ json: { subject: '📊 Weekly leads report: ' + ai.headline, html } }];
"""

nodes = [
    {
        "id": "sched", "name": "Every morning at 9", "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2, "position": [0, 0],
        "parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 9}]}},
    },
    {
        "id": "get", "name": "Get all leads", "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1, "position": [240, 0], "alwaysOutputData": True,
        "parameters": {
            "resource": "row", "operation": "get",
            "dataTableId": {"__rl": True, "mode": "id", "value": LEADS_TABLE},
            "returnAll": True,
        },
    },
    {
        "id": "stats", "name": "Calculate weekly numbers", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [480, 0], "parameters": {"jsCode": STATS},
    },
    {
        "id": "ai", "name": "Gemini: analyse & recommend", "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2, "position": [720, 0],
        "credentials": {"httpHeaderAuth": {"id": GEMINI_CRED, "name": "Gemini API key"}},
        "parameters": {
            "method": "POST",
            "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.gemini_body) }}",
            "options": {"timeout": 60000},
        },
        "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 3000,
    },
    {
        "id": "html", "name": "Build report email", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [960, 0], "parameters": {"jsCode": EMAIL},
    },
    {
        "id": "send", "name": "Email report to Umaima (Brevo)", "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2, "position": [1200, 0],
        "credentials": {"httpHeaderAuth": {"id": BREVO_CRED, "name": "Brevo API key"}},
        "parameters": {
            "method": "POST", "url": "https://api.brevo.com/v3/smtp/email",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ sender: " + json.dumps(OWNER) + ", to: [" + json.dumps(OWNER)
                        + "], subject: $json.subject, htmlContent: $json.html }) }}",
        },
    },
]

connections = {}
for a, b in zip(nodes, nodes[1:]):
    connections[a["name"]] = {"main": [[{"node": b["name"], "type": "main", "index": 0}]]}

wf = {"name": "2. Daily AI Marketing Report", "nodes": nodes, "connections": connections,
      "settings": {"executionOrder": "v1", "timezone": "Asia/Karachi"}}
json.dump(wf, open("workflows/2-daily-ai-marketing-report.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

url, method = (f"{API}/workflows/{WORKFLOW_ID}", "PUT") if WORKFLOW_ID else (f"{API}/workflows", "POST")
req = urllib.request.Request(url, data=json.dumps(wf).encode(), method=method,
                             headers={"X-N8N-API-KEY": KEY, "Content-Type": "application/json"})
try:
    r = json.load(urllib.request.urlopen(req))
    print("saved", r["id"], r["name"])
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:800])
