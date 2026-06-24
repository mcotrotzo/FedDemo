import sys
import os
import shutil
import subprocess
import json
import time
from dotenv import load_dotenv

import BatterySysml
import PVSysml

load_dotenv("repoUrls.env")

REPOS = {
    "simulator": os.getenv("SIMULATOR"),
    "sysml_converter": os.getenv("SYSML_CONVERTER"),
    "fed_tool": os.getenv("FED_TOOL"),
    "digital_twin_manager": os.getenv("DIGITAL_TWIN_MANAGER")
}

DIR_MAPPING = {key: val.split("/")[-1].replace(".git", "") for key, val in REPOS.items() if val}

def run_cmd(cmd, cwd=None, env=None, input_str=None):
    print(f"-> Executing: {' '.join(cmd)} (Directory: {cwd or '.'})")
    current_env = os.environ.copy()
    current_env["PYTHONUNBUFFERED"] = "1"
    if env:
        current_env.update(env)
    proc = subprocess.Popen(cmd, cwd=cwd, env=current_env, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr, text=True)
    proc.communicate(input=input_str)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)

def get_authenticated_url(url):
    username = os.getenv("GITHUB_USERNAME", "")
    password = os.getenv("GITHUB_PASSWORD", "")
    if username and password:
        return url.replace("https://", f"https://{username}:{password}@")
    return url

def fix_line_endings(folder):
    subprocess.run(
        f"find {folder} -type f \\( -name '*.py' -o -name '*.sh' -o -name '*.sysml' \\) -exec sed -i 's/\\r//' {{}} +",
        shell=True, check=False
    )

def setup_environment():
    print("Preparing repositories and dependencies...")
    for name, url in REPOS.items():
        folder = DIR_MAPPING[name]
        if not os.path.exists(folder):
            print(f"Cloning {name}...")
            run_cmd(["git", "clone", get_authenticated_url(url)])
            fix_line_endings(folder)
            req_file = f"{folder}/requirements.txt"
            if os.path.exists(req_file):
                marker = f"{folder}/.deps_installed"
                if not os.path.exists(marker):
                    run_cmd(["pip", "install", "--no-cache-dir", "-r", req_file])
                    open(marker, "w").close()
        else:
            print(f"Skipping clone of {name}, already exists.")
            req_file = f"{folder}/requirements.txt"
            if os.path.exists(req_file):
                marker = f"{folder}/.deps_installed"
                if not os.path.exists(marker):
                    run_cmd(["pip", "install", "--no-cache-dir", "-r", req_file])
                    open(marker, "w").close()

    for folder in [DIR_MAPPING["digital_twin_manager"], DIR_MAPPING["fed_tool"]]:
        shutil.copy("repoUrls.env", f"{folder}/.env")

    credentials_data = {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "aws_region": os.getenv("AWS_REGION", "eu-central-1")
    }

    with open(f"{DIR_MAPPING['digital_twin_manager']}/config_credentials.json", "w") as f:
        json.dump(credentials_data, f, indent=4)

    with open(f"{DIR_MAPPING['fed_tool']}/config_credentials.json", "w") as f:
        json.dump(credentials_data, f, indent=4)

def write_sysml_inputs():
    converter_input_dir = f"{DIR_MAPPING['sysml_converter']}/input/sysml"
    os.makedirs(converter_input_dir, exist_ok=True)

    with open(f"{converter_input_dir}/BatteryTwin.sysml", "w", newline='\n') as f:
        f.write(BatterySysml.getBatterySysmlPath())

    with open(f"{converter_input_dir}/PVTwin.sysml", "w", newline='\n') as f:
        f.write(PVSysml.getPVSysml())

def deploy_twins():
    write_sysml_inputs()

    sysml_folder = DIR_MAPPING["sysml_converter"]
    dt_manager_folder = DIR_MAPPING["digital_twin_manager"]
    fed_tool_folder = DIR_MAPPING["fed_tool"]

    run_cmd(["docker", "compose", "up", "-d"], cwd=f"{sysml_folder}/apiserver")
    time.sleep(10)
    run_cmd(["python", "-m", "src.main", "input/sysml"], cwd=sysml_folder)

    for twin in ["Battery", "PV"]:
        src_output = f"{sysml_folder}/output/{twin}"
        dst_output = f"{dt_manager_folder}/"
        shutil.copytree(src_output, dst_output, dirs_exist_ok=True)

        shutil.copytree("testLambdaFunctions", f"{dt_manager_folder}/src/testLambdaFunctions", dirs_exist_ok=True)

        run_cmd(["python", "main.py"], cwd=f"{dt_manager_folder}/src", input_str="deploy\n")

        src_json = f"{dt_manager_folder}/src/{twin}_federation_input.json"
        dst_json_dir = f"{fed_tool_folder}/input/strategyInputs"
        os.makedirs(dst_json_dir, exist_ok=True)
        shutil.copy(src_json, f"{dst_json_dir}/{twin}_federation_input.json")

def deploy_simulator():
    sim_folder = DIR_MAPPING["simulator"]
    env = {"PULUMI_CONFIG_PASSPHRASE": ""}
    merged_env = {**os.environ.copy(), **env}

    os.makedirs(f"{sim_folder}/input", exist_ok=True)
    credentials_data = {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "aws_region": os.getenv("AWS_REGION", "eu-central-1")
    }
    with open(f"{sim_folder}/input/config_credentials.json", "w") as f:
        json.dump(credentials_data, f, indent=4)

    run_cmd(["pulumi", "login", "--local"], cwd=sim_folder, env=env)
    run_cmd(["pulumi", "package", "add", "terraform-provider", "hashicorp/local"], cwd=sim_folder, env=env)
    subprocess.run(["pulumi", "stack", "init", "dev"], cwd=sim_folder, env=merged_env)
    run_cmd(["pulumi", "up", "--yes"], cwd=sim_folder, env=env)

    res = subprocess.run(["pulumi", "stack", "output", "ec2_public_ip"], cwd=sim_folder, text=True, capture_output=True, env=merged_env)
    ec2_ip = res.stdout.strip()

    print("Simulator deployment done.")
    if ec2_ip:
        print(f"URL: http://{ec2_ip}:5000")

def deploy_fedtwin():
    fed_folder = DIR_MAPPING["fed_tool"]
    run_cmd(["python", "main.py"], cwd=f"{fed_folder}/src")
    
    
    tf_path = f"{fed_folder}/output/main.tf"
    with open(tf_path, "r") as f:
        content = f.read()
    content = content.replace(
        "/home/marcocotrotzo/PycharmProjects/SymlCOnv/input/sysml/testLambdaFunctions",
        "/app/testLambdaFunctions"
    )
    with open(tf_path, "w") as f:
        f.write(content)
    
    run_cmd(["terraform", "init"], cwd=f"{fed_folder}/output")
    run_cmd(["terraform", "apply", "-auto-approve"], cwd=f"{fed_folder}/output")
def destroy(twins=True, simulator=True, fedtwin=True):
    if twins:
        sysml_folder = DIR_MAPPING["sysml_converter"]
        dt_manager_folder = DIR_MAPPING["digital_twin_manager"]
        for twin in ["Battery", "PV"]:
            src_output = f"{sysml_folder}/output/{twin}"
            if not os.path.exists(src_output):
                print(f"Skipping {twin}, output not found.")
                continue
            dst_output = f"{dt_manager_folder}/"
            shutil.copytree(src_output, dst_output, dirs_exist_ok=True)
            shutil.copytree("testLambdaFunctions", f"{dt_manager_folder}/src/testLambdaFunctions", dirs_exist_ok=True)
            subprocess.run(
                ["python", "main.py"],
                cwd=f"{dt_manager_folder}/src",
                input="destroy\n",
                text=True
            )

    if simulator:
        sim_folder = DIR_MAPPING.get("simulator")
        if sim_folder and os.path.exists(sim_folder):
            env = {**os.environ.copy(), "PULUMI_CONFIG_PASSPHRASE": ""}
            subprocess.run(["pulumi", "destroy", "--yes"], cwd=sim_folder, env=env)
    if fedtwin:
        fed_folder = DIR_MAPPING.get("fed_tool")
        if fed_folder and os.path.exists(f"{fed_folder}/output"):
            subprocess.run(["terraform", "destroy", "-auto-approve"], cwd=f"{fed_folder}/output")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py [deploy:twins | deploy:simulator | deploy:fedtwin | destroy | destroy:twins | destroy:simulator | destroy:fedtwin]")
        sys.exit(1)

    action = sys.argv[1]
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