def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_organization_summary(client):
    r = client.get("/api/organization/summary")
    assert r.status_code == 200
    body = r.json()
    assert len(body["repositories"]) == 3


def test_run_knowledge_task(client):
    r = client.post("/api/tasks", json={"objective": "Why does payment-router use this fallback strategy?"})
    assert r.status_code == 200
    assert r.json()["state"]["task_type"] == "knowledge_only"


def test_get_task_after_run(client):
    r = client.post("/api/tasks", json={"objective": "Why does payment-router use this fallback strategy?"})
    task_id = r.json()["task_id"]
    r2 = client.get(f"/api/tasks/{task_id}")
    assert r2.status_code == 200
    assert "audit_trail" in r2.json()["state"]


def test_organization_graph(client):
    r = client.get("/api/organization/graph")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) > 0
