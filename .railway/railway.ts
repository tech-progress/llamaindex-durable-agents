import { defineRailway, github, group, project, service, volume } from "railway/iac";

const repository = process.env.TEMPLATE_SOURCE_REPO ?? "tech-progress/llamaindex-durable-agents";
const branch = process.env.TEMPLATE_SOURCE_BRANCH ?? "release-v1";
const rootDirectory = process.env.TEMPLATE_SOURCE_ROOT ?? "/";
if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error("Source must be owner/repository");
if (!/^[\w.-]+$/.test(branch) || branch.includes("..")) throw new Error("Source branch must be slash-free");
if (!rootDirectory.startsWith("/") || rootDirectory.includes("..")) throw new Error("Source root must be an absolute repository path");
const sourceRoot = rootDirectory.replace(/\/+$/, "") || "/";
const SOURCE = github(repository, { branch, rootDirectory: sourceRoot });
const POSTGRES_IMAGE = "postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652";

export default defineRailway(() => {
  const storage = volume("Postgres Data", { sizeMB: 5000 });
  const postgres = service("Postgres", {
    source: { image: POSTGRES_IMAGE },
    replicas: 1,
    volumeMounts: { "/var/lib/postgresql/data": storage },
    env: {
      PORT: "5432",
      POSTGRES_USER: "workflows",
      POSTGRES_DB: "workflows",
      POSTGRES_PASSWORD: (process.env.TEMPLATE_POSTGRES_PASSWORD ?? "${{secret(32)}}"),
      PGDATA: "/var/lib/postgresql/data/pgdata",
    },
  });
  const api = service("LlamaIndex API", {
    source: SOURCE,
    replicas: 1,
    deploy: { overlapSeconds: 0, drainingSeconds: 10 },
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile", watchPatterns: [sourceRoot === "/" ? "/**" : `${sourceRoot}/**`] },
    start: "/app/start.sh",
    healthcheck: "/readyz",
    healthcheckTimeout: 120,
    env: {
      PORT: "3000",
      DATABASE_URL: "postgresql://${{Postgres.POSTGRES_USER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.POSTGRES_DB}}",
      API_TOKEN: (process.env.TEMPLATE_API_TOKEN ?? "${{secret(48)}}"),
      DBOS_EXECUTOR_PREFIX: "llamaindex-approval",
      PROPOSAL_MODE: "deterministic",
      OPENAI_MODEL: "gpt-4.1-mini-2025-04-14",
      OPENAI_TIMEOUT_SECONDS: "30",
    },
  });
  return project("LlamaIndex durable agents", {
    resources: [group("Workflows", [api]), group("Storage", [postgres, storage])],
  });
});
