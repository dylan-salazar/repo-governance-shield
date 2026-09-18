import os
import sqlite3
import csv
from datetime import datetime
from dotenv import load_dotenv
from github import Github, Auth, GithubException
from tabulate import tabulate

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
TARGET_USER = os.getenv("GITHUB_ORG_OR_USER")

if not TOKEN or not TARGET_USER:
    raise ValueError("Error: GITHUB_TOKEN y GITHUB_ORG_OR_USER deben estar definidos en el archivo .env")

# Autenticacion moderna de PyGithub
auth = Auth.Token(TOKEN)
gh = Github(auth=auth)

DB_NAME = "governance_audit.db"
CSV_NAME = "audit_report.csv"

def init_db():
    """Crea la tabla de auditoria si no existe."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT,
            repo_name TEXT,
            branch_protected INTEGER,
            require_pr INTEGER,
            min_reviews INTEGER,
            has_ci INTEGER,
            compliance_status TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_audit_results(results):
    """Inserta los registros en SQLite y exporta a CSV."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    scan_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    csv_data = []
    headers = ["Scan Date", "Repository", "Branch Protected", "Require PR", "Min Reviews", "Has CI/CD", "Status"]

    for row in results:
        repo, protected, pr, reviews, ci, status = row
        b_protected = 1 if protected == "Sí" else 0
        b_pr = 1 if pr == "Sí" else 0
        b_ci = 1 if ci == "Sí" else 0

        cursor.execute("""
            INSERT INTO audit_history (scan_date, repo_name, branch_protected, require_pr, min_reviews, has_ci, compliance_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (scan_date, repo, b_protected, b_pr, reviews, b_ci, status))

        csv_data.append([scan_date, repo, protected, pr, reviews, ci, status])

    conn.commit()
    conn.close()

    with open(CSV_NAME, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(csv_data)

def audit_repository(repo):
    report = {
        "repo_name": repo.name,
        "branch_protection": False,
        "require_pr": False,
        "required_reviews": 0,
        "has_ci_workflow": False,
        "status": "NO CONFORME"
    }

    try:
        default_branch = repo.get_branch(repo.default_branch)
        if default_branch.protected:
            report["branch_protection"] = True
            protection = default_branch.get_protection()
            if protection.required_pull_request_reviews:
                report["require_pr"] = True
                report["required_reviews"] = protection.required_pull_request_reviews.required_approving_review_count
    except GithubException:
        pass

    try:
        contents = repo.get_contents(".github/workflows")
        if contents:
            report["has_ci_workflow"] = True
    except GithubException:
        report["has_ci_workflow"] = False

    if report["branch_protection"] and report["require_pr"] and report["has_ci_workflow"]:
        report["status"] = "CONFORME"

    return report

def main():
    init_db()
    print(f"\nIniciando auditoria de gobierno sobre repositorios de: {TARGET_USER}...\n")
    try:
        user = gh.get_user(TARGET_USER)
        repos = user.get_repos()
    except GithubException as e:
        print(f"Error de conexion con GitHub: {e}")
        return

    results = []
    for r in repos:
        if not r.fork:
            audit_data = audit_repository(r)
            results.append([
                audit_data["repo_name"],
                "Sí" if audit_data["branch_protection"] else "No",
                "Sí" if audit_data["require_pr"] else "No",
                audit_data["required_reviews"],
                "Sí" if audit_data["has_ci_workflow"] else "No",
                audit_data["status"]
            ])

    headers = ["Repositorio", "Rama Protegida", "Requiere PR", "Reviews Min.", "Tiene CI/CD", "Estado de Gobierno"]
    print(tabulate(results, headers=headers, tablefmt="grid"))
    
    save_audit_results(results)
    print(f"\nAuditoria completada. Datos guardados en '{DB_NAME}' y exportados a '{CSV_NAME}'.")

if __name__ == "__main__":
    main()