"""Generate an AWS ECS/Fargate Terraform baseline and local Docker Compose file."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def _read_topology(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read topology JSON {path}: {exc}") from exc
    return _normalize_topology(value)


def _normalize_topology(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list) or not isinstance(value.get("edges"), list):
        raise ValueError("Topology must be a JSON object with 'nodes' and 'edges' arrays.")
    all_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, node in enumerate(value["nodes"]):
        if not isinstance(node, dict):
            raise ValueError(f"Topology node {index} must be an object.")
        raw_id = node.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ValueError(f"Topology node {index} needs a non-empty string id.")
        node_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw_id).strip("_").lower()
        if not node_id:
            raise ValueError(f"Topology node {index} needs a non-empty id.")
        if node_id in seen:
            raise ValueError(f"Topology has duplicate or colliding node id: {node_id}")
        seen.add(node_id)
        capacity = node.get("capacity_rps", 0)
        if (
            isinstance(capacity, bool)
            or not isinstance(capacity, (int, float))
            or not math.isfinite(capacity)
            or capacity < 0
            or int(capacity) != capacity
        ):
            raise ValueError(f"Topology node {node_id!r} has an invalid capacity_rps.")
        all_nodes.append(
            {
                **node,
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "type": str(node.get("type") or "service").lower(),
                "capacity_rps": int(capacity),
            }
        )
    if not all_nodes:
        raise ValueError("Topology has no nodes; refusing to generate empty infrastructure.")
    nodes = [node for node in all_nodes if not _is_external(node)]
    if not nodes:
        raise ValueError("Topology contains no deployable services or databases.")
    deployable_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    for index, edge in enumerate(value["edges"]):
        if not isinstance(edge, dict):
            raise ValueError(f"Topology edge {index} must be an object.")
        raw_source, raw_target = edge.get("source"), edge.get("target")
        if not isinstance(raw_source, str) or not isinstance(raw_target, str):
            raise ValueError(f"Topology edge {index} needs string source and target IDs.")
        source = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw_source).strip("_").lower()
        target = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw_target).strip("_").lower()
        if source not in seen or target not in seen:
            raise ValueError(f"Topology edge {index} references an unknown node.")
        if source in deployable_ids and target in deployable_ids:
            edges.append({"source": source, "target": target})
    return nodes, edges


def _port(node: dict[str, Any]) -> int:
    value = f"{node['id']} {node['type']}".lower()
    if any(part in value for part in ("postgres", "postgresql")):
        return 5432
    if any(part in value for part in ("mysql", "mariadb")):
        return 3306
    if any(part in value for part in ("redis", "cache", "memcached")):
        return 6379
    if any(part in value for part in ("frontend", "web", "browser")):
        return 3000
    return 8080


def _kind(node: dict[str, Any]) -> str:
    return f"{node['id']} {node['label']} {node['type']}".lower()


def _is_external(node: dict[str, Any]) -> bool:
    return node["type"] in {"browser", "client", "external", "saas", "third_party", "user"} or bool(
        re.search(r"\b(browser|client|external|saas|third.party|user)\b", node["label"], re.I)
    )


def _is_database(node: dict[str, Any]) -> bool:
    return any(part in _kind(node) for part in ("database", "postgres", "mysql", "mariadb"))


def _is_redis(node: dict[str, Any]) -> bool:
    return any(part in _kind(node) for part in ("redis", "cache", "memcached"))


def _database_engine(node: dict[str, Any]) -> str:
    value = _kind(node)
    if "mariadb" in value:
        return "mariadb"
    if "mysql" in value:
        return "mysql"
    return "postgres"


def _is_ingress(node: dict[str, Any], incoming: dict[str, int]) -> bool:
    return incoming[node["id"]] == 0 and any(
        part in _kind(node) for part in ("gateway", "ingress", "load_balancer", "proxy", "frontend", "web")
    )


def _tf_services(nodes: list[dict[str, Any]]) -> str:
    entries = []
    for node in nodes:
        entries.append(
            f'    {json.dumps(node["id"])} = {{\n'
            f"      container_port = {_port(node)}\n"
            f"      capacity_rps   = {node['capacity_rps']}\n"
            "    }"
        )
    return "\n".join(entries)


def _tf_databases(nodes: list[dict[str, Any]]) -> str:
    entries = []
    for node in nodes:
        if not _is_database(node):
            continue
        engine = _database_engine(node)
        entries.append(
            f'    {json.dumps(node["id"])} = {{\n'
            f'      engine = "{engine}"\n'
            f"      port   = {_port(node)}\n"
            "    }"
        )
    return "\n".join(entries)


def _terraform_main(nodes: list[dict[str, Any]]) -> str:
    app_nodes = [node for node in nodes if not _is_database(node)]
    service_values = _tf_services(app_nodes)
    database_values = _tf_databases(nodes)
    return f'''# Generated baseline: private AWS ECS/Fargate services and managed RDS databases.
# Review network, secrets, scaling, image, and application health requirements before deployment.
terraform {{
  required_version = ">= 1.5.0"
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }}
  }}
}}

provider "aws" {{
  region = var.aws_region
}}

locals {{
  services = {{
{service_values}
  }}
  databases = {{
{database_values}
  }}
}}

resource "aws_ecs_cluster" "platform" {{
  name = var.cluster_name
}}

resource "aws_service_discovery_private_dns_namespace" "internal" {{
  name        = "${{var.cluster_name}}.local"
  description = "Private service discovery for ${{var.cluster_name}}"
  vpc         = var.vpc_id
}}

resource "aws_cloudwatch_log_group" "service" {{
  for_each          = local.services
  name              = "/ecs/${{var.cluster_name}}/${{each.key}}"
  retention_in_days = var.log_retention_days
}}

resource "aws_iam_role" "task_execution" {{
  name = "${{var.cluster_name}}-task-execution"
  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect    = "Allow"
      Principal = {{ Service = "ecs-tasks.amazonaws.com" }}
      Action    = "sts:AssumeRole"
    }}]
  }})
}}

resource "aws_iam_role_policy_attachment" "task_execution" {{
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}}

resource "aws_security_group" "tasks" {{
  name        = "${{var.cluster_name}}-tasks"
  description = "Private task-to-task traffic for ECS Service Connect"
  vpc_id      = var.vpc_id
}}

resource "aws_vpc_security_group_ingress_rule" "service_connect" {{
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.tasks.id
  description                  = "Allow traffic only between this service's tasks"
  ip_protocol                  = "tcp"
  from_port                    = 1
  to_port                      = 65535
}}

resource "aws_vpc_security_group_egress_rule" "task_egress" {{
  security_group_id = aws_security_group.tasks.id
  description       = "Task egress; restrict this rule to approved dependencies before production"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}}

resource "aws_db_subnet_group" "platform" {{
  count      = length(local.databases) > 0 ? 1 : 0
  name       = "${{var.cluster_name}}-databases"
  subnet_ids = var.private_subnet_ids
}}

resource "aws_security_group" "databases" {{
  name        = "${{var.cluster_name}}-databases"
  description = "Allow database traffic only from platform ECS tasks"
  vpc_id      = var.vpc_id
}}

resource "aws_vpc_security_group_ingress_rule" "database" {{
  for_each                     = local.databases
  security_group_id            = aws_security_group.databases.id
  referenced_security_group_id = aws_security_group.tasks.id
  description                  = "ECS task access to ${{each.key}}"
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}}

resource "aws_db_instance" "database" {{
  for_each               = local.databases
  identifier             = "${{var.cluster_name}}-${{each.key}}"
  engine                 = each.value.engine
  instance_class         = var.database_instance_class
  allocated_storage      = var.database_storage_gb
  max_allocated_storage  = var.database_max_storage_gb
  storage_type           = "gp3"
  storage_encrypted      = true
  multi_az               = var.database_multi_az
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.platform[0].name
  vpc_security_group_ids = [aws_security_group.databases.id]
  username               = var.database_username
  manage_master_user_password = true
  backup_retention_period     = var.database_backup_days
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier  = "${{var.cluster_name}}-${{each.key}}-final"
  copy_tags_to_snapshot       = true

  tags = {{
    Name = "${{var.cluster_name}}-${{each.key}}"
  }}
}}

resource "aws_ecs_task_definition" "service" {{
  for_each                 = local.services
  family                   = "${{var.cluster_name}}-${{each.key}}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  container_definitions = jsonencode([{{
    name      = each.key
    image     = var.container_images[each.key]
    essential = true
    portMappings = [{{
      name          = "http"
      containerPort = each.value.container_port
      hostPort      = each.value.container_port
      protocol      = "tcp"
    }}]
    logConfiguration = {{
      logDriver = "awslogs"
      options = {{
        awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "container"
      }}
    }}
  }}])
}}

resource "aws_ecs_service" "service" {{
  for_each                           = local.services
  name                               = each.key
  cluster                            = aws_ecs_cluster.platform.id
  task_definition                    = aws_ecs_task_definition.service[each.key].arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  network_configuration {{
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }}

  service_connect_configuration {{
    enabled   = true
    namespace = aws_service_discovery_private_dns_namespace.internal.arn
    service {{
      port_name      = "http"
      discovery_name = each.key
      client_alias {{
        dns_name = each.key
        port     = each.value.container_port
      }}
    }}
  }}

  depends_on = [aws_iam_role_policy_attachment.task_execution]
}}

output "cluster_name" {{
  description = "ECS cluster hosting the generated services."
  value       = aws_ecs_cluster.platform.name
}}

output "service_connect_namespace" {{
  description = "Private DNS suffix for ECS Service Connect."
  value       = aws_service_discovery_private_dns_namespace.internal.name
}}

output "service_names" {{
  description = "Internal service names; resolve as <name>.<cluster_name>.local."
  value       = sort(keys(local.services))
}}

output "database_connection_metadata" {{
  description = "Private RDS endpoints and managed master-secret ARNs."
  value = {{
    for name, database in aws_db_instance.database : name => {{
      address           = database.address
      port              = database.port
      master_secret_arn = database.master_user_secret[0].secret_arn
    }}
  }}
}}
'''


def _variables_tf(nodes: list[dict[str, Any]]) -> str:
    keys = ", ".join(json.dumps(node["id"]) for node in nodes if not _is_database(node))
    return f'''variable "aws_region" {{
  description = "AWS region for the ECS cluster and CloudWatch logs."
  type        = string
}}

variable "cluster_name" {{
  description = "Name prefix for ECS, service discovery, IAM, and logs."
  type        = string
  default     = "stress-arch"
}}

variable "vpc_id" {{
  description = "Existing VPC ID containing the private subnets."
  type        = string
}}

variable "private_subnet_ids" {{
  description = "At least two private subnet IDs in distinct availability zones."
  type        = list(string)
  validation {{
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Provide at least two private subnet IDs."
  }}
}}

variable "container_images" {{
  description = "Container image URI for every topology service: {keys}."
  type        = map(string)
  validation {{
    condition = alltrue([
      for image in values(var.container_images) : length(trimspace(image)) > 0
    ]) && alltrue([
      for service in [{keys}] : contains(keys(var.container_images), service)
    ])
    error_message = "Set a non-empty container image URI for every generated service."
  }}
}}

variable "desired_count" {{
  description = "Number of Fargate tasks per service."
  type        = number
  default     = 2
  validation {{
    condition     = var.desired_count >= 1
    error_message = "desired_count must be at least one."
  }}
}}

variable "task_cpu" {{
  description = "Fargate task CPU units; choose a valid Fargate CPU/memory pair."
  type        = number
  default     = 512
}}

variable "task_memory" {{
  description = "Fargate task memory in MiB; choose a valid Fargate CPU/memory pair."
  type        = number
  default     = 1024
}}

variable "log_retention_days" {{
  description = "CloudWatch log retention period."
  type        = number
  default     = 30
}}

variable "database_instance_class" {{
  description = "RDS instance class for generated database nodes."
  type        = string
  default     = "db.t4g.micro"
}}

variable "database_storage_gb" {{
  description = "Initial encrypted RDS storage in GiB."
  type        = number
  default     = 20
}}

variable "database_max_storage_gb" {{
  description = "Maximum autoscaled RDS storage in GiB."
  type        = number
  default     = 100
}}

variable "database_multi_az" {{
  description = "Enable RDS Multi-AZ deployments for availability."
  type        = bool
  default     = true
}}

variable "database_username" {{
  description = "Master username; AWS manages its password in Secrets Manager."
  type        = string
  default     = "app"
}}

variable "database_backup_days" {{
  description = "RDS automated backup retention days (1 through 35)."
  type        = number
  default     = 7
  validation {{
    condition     = var.database_backup_days >= 1 && var.database_backup_days <= 35
    error_message = "database_backup_days must be between 1 and 35."
  }}
}}
'''


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _compose(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], incoming: dict[str, int]
) -> str:
    networks: dict[tuple[str, str], str] = {}
    for edge in edges:
        pair = tuple(sorted((edge["source"], edge["target"])))
        networks.setdefault(pair, f"link_{pair[0]}_{pair[1]}")
    if not networks:
        networks[("platform", "internal")] = "platform_internal"
    node_networks: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for (source, target), network in networks.items():
        if source in node_networks:
            node_networks[source].append(network)
        if target in node_networks and target != source:
            node_networks[target].append(network)

    lines = ["name: stress-arch", "services:"]
    for index, node in enumerate(nodes):
        node_id = node["id"]
        env_prefix = re.sub(r"[^A-Z0-9]+", "_", node_id.upper()).strip("_")
        kind = _kind(node)
        if _is_database(node):
            default_image = {
                "mariadb": "mariadb:11",
                "mysql": "mysql:8.4",
                "postgres": "postgres:16-alpine",
            }[_database_engine(node)]
            image = str(node.get("image") or default_image)
        elif "redis" in kind or node["type"] == "cache":
            image = str(node.get("image") or "redis:7-alpine")
        else:
            image = str(node.get("image") or f"${{APP_{env_prefix}_IMAGE:?Set APP_{env_prefix}_IMAGE}}")
        lines.extend(
            [
                f"  {_yaml_scalar(node_id)}:",
                f"    image: {_yaml_scalar(image)}",
                "    restart: unless-stopped",
                "    init: true",
                "    deploy:",
                "      resources:",
                "        limits:",
                "          cpus: \"1.0\"",
                "          memory: \"512M\"",
                "    logging:",
                "      driver: json-file",
                "      options:",
                "        max-size: \"10m\"",
                "        max-file: \"3\"",
                "    expose:",
                f"      - {_port(node)}",
            ]
        )
        if _is_database(node) and _database_engine(node) in {"mariadb", "mysql"}:
            lines.extend(
                [
                    "    environment:",
                    '      MYSQL_DATABASE: "${MYSQL_DATABASE:-app}"',
                    '      MYSQL_USER: "${MYSQL_USER:-app}"',
                    '      MYSQL_PASSWORD: "${MYSQL_PASSWORD:?Set MYSQL_PASSWORD}"',
                    '      MYSQL_ROOT_PASSWORD: "${MYSQL_ROOT_PASSWORD:?Set MYSQL_ROOT_PASSWORD}"',
                    "    volumes:",
                    f"      - {node_id}_data:/var/lib/mysql",
                    "    healthcheck:",
                    '      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]',
                    "      interval: 10s",
                    "      timeout: 5s",
                    "      retries: 5",
                ]
            )
        elif _is_database(node):
            lines.extend(
                [
                    "    environment:",
                    '      POSTGRES_DB: "${POSTGRES_DB:-app}"',
                    '      POSTGRES_USER: "${POSTGRES_USER:-app}"',
                    '      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}"',
                    "    volumes:",
                    f"      - {node_id}_data:/var/lib/postgresql/data",
                    "    healthcheck:",
                    '      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]',
                    "      interval: 10s",
                    "      timeout: 5s",
                    "      retries: 5",
                ]
            )
        elif _is_redis(node):
            lines.extend(
                [
                    "    healthcheck:",
                    '      test: ["CMD", "redis-cli", "ping"]',
                    "      interval: 10s",
                    "      timeout: 3s",
                    "      retries: 5",
                ]
            )
        if _is_ingress(node, incoming):
            lines.extend(
                [
                    "    ports:",
                    f'      - "${{APP_{env_prefix}_HOST_PORT:-{8080 + index}}}:{_port(node)}"',
                ]
            )
        lines.append("    networks:")
        for network in sorted(set(node_networks[node_id])):
            lines.append(f"      - {network}")
        lines.append("")

    volume_nodes = [node for node in nodes if _is_database(node)]
    if volume_nodes:
        lines.append("volumes:")
        for node in volume_nodes:
            lines.append(f"  {_yaml_scalar(node['id'] + '_data')}:")
        lines.append("")
    lines.append("networks:")
    for network in sorted(set(networks.values())):
        lines.extend([f"  {_yaml_scalar(network)}:", "    driver: bridge"])
    return "\n".join(lines) + "\n"


def generate_files(topology: dict[str, Any], output_dir: Path) -> dict[str, str]:
    """Generate deployment files for a canonical topology and return their contents."""
    nodes, edges = _normalize_topology(topology)
    incoming = {node["id"]: 0 for node in nodes}
    for edge in edges:
        incoming[edge["target"]] += 1
    files = {
        "main.tf": _terraform_main(nodes),
        "variables.tf": _variables_tf(nodes),
        "docker-compose.yml": _compose(nodes, edges, incoming),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AWS Terraform and Docker Compose from topology JSON.")
    parser.add_argument("topology", type=Path, help="Approved canonical topology JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for main.tf, variables.tf, and docker-compose.yml (default: ./output).",
    )
    args = parser.parse_args()
    try:
        topology = json.loads(args.topology.read_text(encoding="utf-8-sig"))
        if not isinstance(topology, dict):
            raise ValueError("Topology must be a JSON object.")
        files = generate_files(topology, args.output_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"generate_iac: {exc}\n")
    print(f"Wrote {', '.join(files)} to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
