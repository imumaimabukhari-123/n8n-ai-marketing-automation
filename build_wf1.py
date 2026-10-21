"""Builds workflow 1 (AI lead follow-up) and pushes it to the local n8n."""
import json, sys, urllib.request

API = "http://localhost:5678/api/v1"
KEY = open(sys.argv[1]).read().strip()
GEMINI_CRED = sys.argv[2]
LEADS_TABLE = sys.argv[3]
BREVO_CRED = sys.argv[4]
WORKFLOW_ID = sys.argv[5] if len(sys.argv) > 5 else None
OWNER = {"name": "Umaima", "email": "imumaimabukhari@gmail.com"}

PREPARE = r"""
// Turn the form answers into a clean lead + the Gemini request body
const f = $input.first().json;
const lead = {
  name: f['Full name'] || '',
  email: f['Email'] || '',
  company: f['Company'] || '',
  website: f['Website'] || '',
  service: f['What do you need help with?'] || '',
  budget: f['Budget'] || '',
  message: f['Tell me about your project'] || '',
};

const prompt = `You are the sales assistant for Syeda Umaima, a software engineer who builds
Shopify stores, AI chatbots, AI automations (n8n), Chrome extensions and MERN web apps.

A new lead filled in the contact form:
${JSON.stringify(lead, null, 2)}

1. Score the lead from 0 to 100 (budget, clear need, fit with her services, real business).
2. temperature: "hot" (70+), "warm" (40-69) or "cold" (under 40).
3. summary: one sentence for Umaima about this lead.
4. Write a short, warm, personal follow-up email FROM Umaima TO the lead:
   mention their project, suggest one concrete idea, invite them to a 15-minute call.
   Plain text, max 120 words, sign off as "Umaima". No placeholders.`;

const gemini_body = {
  contents: [{ parts: [{ text: prompt }] }],
  generationConfig: {
    responseMimeType: 'application/json',
    responseSchema: {
      type: 'OBJECT',
      properties: {
        score: { type: 'INTEGER' },
        temperature: { type: 'STRING', enum: ['hot', 'warm', 'cold'] },
        summary: { type: 'STRING' },
        email_subject: { type: 'STRING' },
        email_body: { type: 'STRING' },
      },
      required: ['score', 'temperature', 'summary', 'email_subject', 'email_body'],
    },
  },
};

return [{ json: { ...lead, gemini_body } }];
"""

PARSE = r"""
// Read Gemini's JSON answer and combine it with the lead
const lead = $('Prepare lead for AI').first().json;
const text = $input.first().json.candidates?.[0]?.content?.parts?.[0]?.text || '{}';
const ai = JSON.parse(text);
const { gemini_body, ...clean } = lead;
return [{ json: {
  ...clean,
  score: ai.score,
  temperature: ai.temperature,
  summary: ai.summary,
  email_subject: ai.email_subject,
  email_body: ai.email_body,
  email_sent: false,
} }];
"""

MARK_SENT = r"""
// The email went out: mark the lead as contacted before saving it
const lead = $('Read AI result').first().json;
return [{ json: { ...lead, email_sent: true } }];
"""

def brevo_body(to, subject, text):
    return "={{ JSON.stringify({ sender: " + json.dumps(OWNER) + ", to: [" + to + "], subject: " + subject + ", textContent: " + text + " }) }}"

def brevo_node(id_, name, pos, body):
    return {
        "id": id_, "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": pos,
        "credentials": {"httpHeaderAuth": {"id": BREVO_CRED, "name": "Brevo API key"}},
        "parameters": {
            "method": "POST", "url": "https://api.brevo.com/v3/smtp/email",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "specifyBody": "json", "jsonBody": body,
        },
    }

def opt(*xs):
    return {"values": [{"option": x} for x in xs]}

nodes = [
    {
        "id": "form", "name": "Lead form", "type": "n8n-nodes-base.formTrigger",
        "typeVersion": 2.2, "position": [0, 0], "webhookId": "a1c3e5f7-lead-form-0001",
        "parameters": {
            "formTitle": "Work with Umaima",
            "formDescription": "Tell me about your project and I'll get back to you with ideas within 24 hours.",
            "formFields": {"values": [
                {"fieldLabel": "Full name", "requiredField": True},
                {"fieldLabel": "Email", "fieldType": "email", "requiredField": True},
                {"fieldLabel": "Company"},
                {"fieldLabel": "Website"},
                {"fieldLabel": "What do you need help with?", "fieldType": "dropdown", "requiredField": True,
                 "fieldOptions": opt("Shopify store", "AI chatbot", "Workflow automation (n8n)",
                                     "Chrome extension", "Web app (MERN)", "Something else")},
                {"fieldLabel": "Budget", "fieldType": "dropdown", "requiredField": True,
                 "fieldOptions": opt("Under $500", "$500 - $2,000", "$2,000 - $5,000", "$5,000+")},
                {"fieldLabel": "Tell me about your project", "fieldType": "textarea", "requiredField": True},
            ]},
            "options": {"respondWithOptions": {"values": {
                "formSubmittedText": "Thank you! Check your inbox, you'll hear from me shortly."}}},
        },
    },
    {
        "id": "prep", "name": "Prepare lead for AI", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [240, 0], "parameters": {"jsCode": PREPARE},
    },
    {
        "id": "ai", "name": "Gemini: score lead & write email", "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2, "position": [480, 0],
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
        "id": "parse", "name": "Read AI result", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [720, 0], "parameters": {"jsCode": PARSE},
    },
    brevo_node("send", "Send follow-up email (Brevo)", [960, 0], brevo_body(
        "{ email: $json.email, name: $json.name }", "$json.email_subject", "$json.email_body")),
    {
        "id": "mark", "name": "Mark as emailed", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [1200, 0], "parameters": {"jsCode": MARK_SENT},
    },
    {
        "id": "save", "name": "Save lead to CRM table", "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1, "position": [1440, 0],
        "parameters": {
            "resource": "row", "operation": "insert",
            "dataTableId": {"__rl": True, "mode": "id", "value": LEADS_TABLE},
            "columns": {"mappingMode": "autoMapInputData", "value": {}},
        },
    },
    {
        "id": "hot", "name": "Is it a hot lead?", "type": "n8n-nodes-base.if",
        "typeVersion": 2.2, "position": [1680, 0],
        "parameters": {"conditions": {
            "options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
            "combinator": "and",
            "conditions": [{"id": "c1", "leftValue": "={{ $json.temperature }}", "rightValue": "hot",
                            "operator": {"type": "string", "operation": "equals"}}],
        }, "options": {}},
    },
    brevo_node("alert", "Alert Umaima about hot lead", [1920, -100], brevo_body(
        json.dumps(OWNER),
        "'🔥 Hot lead: ' + $json.name + ' (' + $json.score + '/100)'",
        r"'New hot lead!\n\n' + $json.summary + '\n\nName: ' + $json.name + '\nEmail: ' + $json.email + "
        r"'\nCompany: ' + $json.company + '\nService: ' + $json.service + '\nBudget: ' + $json.budget + "
        r"'\n\nTheir message:\n' + $json.message + '\n\nA follow-up email was already sent to them.'")),
]

connections = {}
for a, b in zip(nodes, nodes[1:-1]):
    connections[a["name"]] = {"main": [[{"node": b["name"], "type": "main", "index": 0}]]}
connections["Is it a hot lead?"] = {"main": [[{"node": "Alert Umaima about hot lead", "type": "main", "index": 0}], []]}

wf = {"name": "1. AI Lead Follow-up", "nodes": nodes, "connections": connections,
      "settings": {"executionOrder": "v1"}}
json.dump(wf, open("workflows/1-ai-lead-follow-up.json", "w"), indent=2)

url, method = (f"{API}/workflows/{WORKFLOW_ID}", "PUT") if WORKFLOW_ID else (f"{API}/workflows", "POST")
req = urllib.request.Request(url, data=json.dumps(wf).encode(), method=method,
                             headers={"X-N8N-API-KEY": KEY, "Content-Type": "application/json"})
try:
    r = json.load(urllib.request.urlopen(req))
    print("saved", r["id"], r["name"])
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:800])
