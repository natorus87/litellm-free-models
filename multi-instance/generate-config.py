#!/usr/bin/env python3
"""
Generate master config.yaml from the base config.yaml for both Docker and K8s.

For each model_name in model_list, additional deployments are added that route
through each slave LiteLLM instance. This doubles/triples the effective rate
limits because each slave has its own set of provider API keys.

Docker output:  master/config.yaml
K8s   output:  k8s/master/configmap.yaml
"""

import os

BASE_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

# Docker Compose: slaves reachable by container-on-bridge-network name
DOCKER_SLAVES = [
    ("slave1", "http://slave1:4000", "SLAVE1_API_KEY"),
    ("slave2", "http://slave2:4000", "SLAVE2_API_KEY"),
]

# Kubernetes: slaves reachable by K8s Service DNS name
K8S_SLAVES = [
    ("slave-1", "http://litellm-slave-1:4000", "SLAVE1_API_KEY"),
    ("slave-2", "http://litellm-slave-2:4000", "SLAVE2_API_KEY"),
]

DOCKER_OUTPUT = os.path.join(os.path.dirname(__file__), "master", "config.yaml")
K8S_OUTPUT = os.path.join(os.path.dirname(__file__), "k8s", "master", "configmap.yaml")
K8S_SLAVE_OUTPUT = os.path.join(os.path.dirname(__file__), "k8s", "slave", "configmap.yaml")

K8S_NAMESPACE = "litellm-free-models"


def parse_model_list(lines):
    model_list_start = None
    model_list_end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "model_list:" and not line.startswith(" "):
            model_list_start = i
        elif model_list_start is not None and i > model_list_start:
            if stripped and not line.startswith(" ") and not stripped.startswith("#"):
                model_list_end = i
                break
    if model_list_end is None:
        model_list_end = len(lines)

    entries = []
    current = None
    for line in lines[model_list_start + 1 : model_list_end]:
        if line.strip().startswith("- model_name:"):
            if current is not None:
                entries.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        entries.append(current)

    return entries, model_list_start, model_list_end


def extract_model_name(entry_lines):
    for line in entry_lines:
        if line.strip().startswith("- model_name:"):
            return line.split("model_name:")[1].strip()


def generate_slave_entries(model_names, slaves):
    entries = []
    for mn in model_names:
        for _name, url, env_var in slaves:
            entries.append(f"  - model_name: {mn}\n")
            entries.append(f"    litellm_params:\n")
            entries.append(f"      model: openai/{mn}\n")
            entries.append(f"      api_key: os.environ/{env_var}\n")
            entries.append(f"      api_base: {url}\n")
    return entries


def write_plain_yaml(lines, slave_entries, ml_end, path):
    output = lines[:ml_end] + slave_entries + lines[ml_end:]
    with open(path, "w") as f:
        f.writelines(output)
    print(f"  Wrote {path} ({sum(1 for _ in open(path))} lines)")


def write_configmap_yaml(lines, slave_entries, ml_end, path, name, component):
    config_content = "".join(lines[:ml_end] + slave_entries + lines[ml_end:])
    indented = "    " + config_content.replace("\n", "\n    ").rstrip("    ") + "\n"

    cm = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {name}
  namespace: {K8S_NAMESPACE}
  labels:
    app.kubernetes.io/name: litellm-free-models
    app.kubernetes.io/component: {component}
data:
  config.yaml: |
{indented}"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(cm)
    print(f"  Wrote {path} ({sum(1 for _ in open(path))} lines)")


def write_slave_configmap(lines, path):
    config_content = "".join(lines)
    indented = "    " + config_content.replace("\n", "\n    ").rstrip("    ") + "\n"

    cm = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-slave-config
  namespace: {K8S_NAMESPACE}
  labels:
    app.kubernetes.io/name: litellm-free-models
    app.kubernetes.io/component: slave
data:
  config.yaml: |
{indented}"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(cm)
    print(f"  Wrote {path} ({sum(1 for _ in open(path))} lines)")


def generate(slaves, output_path, k8s_configmap=False):
    with open(BASE_CONFIG) as f:
        lines = f.readlines()

    entries, ml_start, ml_end = parse_model_list(lines)

    seen = set()
    model_names = []
    for entry in entries:
        mn = extract_model_name(entry)
        if mn not in seen:
            seen.add(mn)
            model_names.append(mn)

    slave_entries = generate_slave_entries(model_names, slaves)

    total_after = len(entries) + len(slave_entries) // 5
    label = "ConfigMap" if k8s_configmap else "config"
    print(f"  [{label}] {len(entries)} base + {len(slave_entries) // 5} slave = {total_after} total deployments")

    if k8s_configmap:
        write_configmap_yaml(lines, slave_entries, ml_end, output_path,
                             name="litellm-master-config", component="master")
    else:
        write_plain_yaml(lines, slave_entries, ml_end, output_path)


def main():
    print("Generating Docker master config...")
    generate(DOCKER_SLAVES, DOCKER_OUTPUT, k8s_configmap=False)

    print("Generating K8s master ConfigMap...")
    generate(K8S_SLAVES, K8S_OUTPUT, k8s_configmap=True)

    print("Generating K8s slave ConfigMap (base config)...")
    with open(BASE_CONFIG) as f:
        lines = f.readlines()
    write_slave_configmap(lines, K8S_SLAVE_OUTPUT)

    print("Done.")


if __name__ == "__main__":
    main()
