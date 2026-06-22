import sys
import os
import shutil
import subprocess
import json
import time
from dotenv import load_dotenv

# Importiere deine SysML String-Generatoren
import BatterySysml
import PVSysml

# Lade Umgebungsvariablen aus repoUrls.env
load_dotenv("repoUrls.env")

REPOS = {
    "simulator": os.getenv("SIMULATOR"),
    "sysml_converter": os.getenv("SYSML_CONVERTER"),
    "fed_tool": os.getenv("FED_TOOL"),
    "digital_twin_manager": os.getenv("DIGITAL_TWIN_MANAGER")
}

# Ordnernamen basierend auf den URLs extrahieren (z.B. FedSysML)
DIR_MAPPING = {key: val.split("/")[-1].replace(".git", "") for key, val in REPOS.items() if val}

def run_cmd(cmd, cwd=None, env=None, input_str=None):
    """Führt CLI-Befehle aus und bricht bei Fehlern sofort ab."""
    print(f"-> Executing: {' '.join(cmd)} (Directory: {cwd or '.'})")
    current_env = os.environ.copy()
    if env:
        current_env.update(env)
    
    subprocess.run(cmd, cwd=cwd, env=current_env, input=input_str, text=True, check=True)

def setup_environment():
    print("Preparing repositories and dependencies...")
    
    # 1. Klone alle Repositories, falls sie noch nicht existieren
    for name, url in REPOS.items():
        folder = DIR_MAPPING[name]
        if not os.path.exists(folder):
            print(f"Cloning {name} from {url}...")
            run_cmd(["git", "clone", url])
            
            # Python-Abhängigkeiten des frisch geklonten Repos installieren
            req_file = f"{folder}/requirements.txt"
            if os.path.exists(req_file):
                run_cmd(["pip", "install", "--no-cache-dir", "-r", req_file])

    # 2. .env Datei in die Repositories kopieren (für AWS Variablen im Prozess)
    for folder in [DIR_MAPPING["digital_twin_manager"], DIR_MAPPING["fed_tool"]]:
        shutil.copy("repoUrls.env", f"{folder}/.env")
        
    # 3. config_credentials.json dynamisch aus den Umgebungsvariablen bauen
    print("Generating config_credentials.json dynamically...")
    
    credentials_data = {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "region": os.getenv("AWS_REGION", "eu-central-1")
    }
    
    # Pfade, wo die Repositories die JSON-Datei erwarten
    dt_manager_path = DIR_MAPPING["digital_twin_manager"]
    fed_tool_path = DIR_MAPPING["fed_tool"]
    
    # JSON direkt in den digital-twin-manager schreiben
    with open(f"{dt_manager_path}/config_credentials.json", "w") as f:
        json.dump(credentials_data, f, indent=4)
        
    # JSON direkt in das FedSysML-Tool schreiben
    with open(f"{fed_tool_path}/config_credentials.json", "w") as f:
        json.dump(credentials_data, f, indent=4)
        
    print("✅ config_credentials.json successfully generated inside target repositories.")

def write_sysml_inputs():
    """Schreibt die SysML-Strings aus deinen Python-Dateien in den Konverter-Input."""
    converter_input_dir = f"{DIR_MAPPING['sysml_converter']}/input/sysml"
    os.makedirs(converter_input_dir, exist_ok=True)
    
    with open(f"{converter_input_dir}/BatteryTwin.sysml", "w") as f:
        f.write(BatterySysml.getBatterySysmlPath())
        
    with open(f"{converter_input_dir}/PVTwin.sysml", "w") as f:
        f.write(PVSysml.getPVSysml())
    print("✅ SysML files generated successfully inside converter.")

def deploy_twins():
    write_sysml_inputs()
    
    sysml_folder = DIR_MAPPING["sysml_converter"]
    dt_manager_folder = DIR_MAPPING["digital_twin_manager"]
    fed_tool_folder = DIR_MAPPING["fed_tool"]

    print("🚀 Phase 1: Deploying Twins...")
    # API Server des Konverters starten
    run_cmd(["docker", "compose", "up", "-d"], cwd=f"{sysml_folder}/apiserver")
    
    print("⏳ Waiting 10 seconds for sysml-kernel-container to initialize...")
    time.sleep(10)
    # Konverter ausführen
    run_cmd(["python", "-m", "src.main", "input/sysml"], cwd=sysml_folder)
    
    # Twins verarbeiten loop
    for twin in ["Battery", "PV"]:
        # Output-Dateien kopieren
        src_output = f"{sysml_folder}/output/{twin}"
        dst_output = f"{dt_manager_folder}/"
        shutil.copytree(src_output, dst_output, dirs_exist_ok=True)
        
        # Digital Twin Manager starten ("deploy" übergeben)
        run_cmd(["python", "main.py"], cwd=f"{dt_manager_folder}/src", input_str="deploy\n")
        
        # Output des Managers in den Föderations-Core verschieben
        src_json = f"{dt_manager_folder}/src/{twin}_federation_input.json"
        dst_json_dir = f"{fed_tool_folder}/input/strategyInputs"
        os.makedirs(dst_json_dir, exist_ok=True)
        shutil.copy(src_json, f"{dst_json_dir}/{twin}_federation_input.json")

def deploy_simulator():
    sim_folder = DIR_MAPPING["simulator"]
    print("🚀 Phase 2: Deploying CloudDeployer & Simulator...")
    
    env = {"PULUMI_CONFIG_PASSPHRASE": ""}
    run_cmd(["pulumi", "login", "--local"], cwd=sim_folder, env=env)
    run_cmd(["pulumi", "package", "add", "terraform-provider", "hashicorp/local"], cwd=sim_folder, env=env)
    
    # Init Stack (ohne check=True, falls er bereits existiert)
    subprocess.run(["pulumi", "stack", "init", "dev"], cwd=sim_folder, env=os.environ.copy().update(env))
    run_cmd(["pulumi", "up", "--yes"], cwd=sim_folder, env=env)
    
    # IP-Adresse auslesen
    res = subprocess.run(["pulumi", "stack", "output", "ec2_public_ip"], cwd=sim_folder, text=True, capture_output=True, env=os.environ.copy().update(env))
    ec2_ip = res.stdout.strip()
    
    print("==================================================")
    print("🚀 Simulator-Deployment erfolgreich!")
    if ec2_ip:
        print(f"🔗 URL: http://{ec2_ip}:5000")
    print("==================================================")

def deploy_fedtwin():
    fed_folder = DIR_MAPPING["fed_tool"]
    print("🚀 Phase 3: Running Federation Twin Core...")
    
    run_cmd(["python", "main.py"], cwd=f"{fed_folder}/src")
    run_cmd(["terraform", "init"], cwd=f"{fed_folder}/output")
    run_cmd(["terraform", "apply", "-auto-approve"], cwd=f"{fed_folder}/output")

def destroy(twins=True, simulator=True, fedtwin=True):
    print("💥 Destroying everything...")

    if twins:
        print("-> Destroying Twins...")
        dt_manager_folder = DIR_MAPPING["digital_twin_manager"]
        run_cmd(["python", "main.py"], cwd=f"{dt_manager_folder}/src", input_str="destroy\n")

    if simulator:
        # 1. Simulator via Pulumi loeschen
        sim_folder = DIR_MAPPING.get("simulator")
        if sim_folder and os.path.exists(sim_folder):
            subprocess.run(["pulumi", "destroy", "--yes"], cwd=sim_folder, env={"PULUMI_CONFIG_PASSPHRASE": ""})
        
    if fedtwin:
        # 2. Föderation via Terraform loeschen
        fed_folder = DIR_MAPPING.get("fed_tool")
        if fed_folder and os.path.exists(f"{fed_folder}/output"):
            subprocess.run(["terraform", "destroy", "-auto-approve"], cwd=f"{fed_folder}/output")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py [deploy:twins | deploy:simulator | deploy:fedtwin | destroy | destroy:twins | destroy:simulator | destroy:fedtwin]")
        sys.exit(1)
        
    action = sys.argv[1]
    
    # setup_environment wird bei Zerstörung nicht zwingend benötigt
    if action != "destroy":
        setup_environment()
        
    if action == "deploy:twins":
        deploy_twins()
    elif action == "deploy:simulator":
        deploy_simulator()
    elif action == "deploy:fedtwin":
        deploy_fedtwin()
    elif action == "destroy":
        destroy()
    elif action == "destroy:twins":
        destroy(twins=True, simulator=False, fedtwin=False)
    elif action == "destroy:simulator":
        destroy(twins=False, simulator=True, fedtwin=False)
    elif action == "destroy:fedtwin":
        destroy(twins=False, simulator=False, fedtwin=True)
    else:
        print(f"Unknown action: {action}")