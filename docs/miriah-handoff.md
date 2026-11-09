# Miriah handoff

T202 source integration is unblocked by deployment: the backend source base is available locally at commit `0863048`, and source work can proceed without an app deployment. The Friction Desk application is **not claimed to be deployed**.

The frontend source was reported as untracked in the shared `kubecon-hackathon` worktree. This IaC change has not touched that worktree or imported those files. Before source merge, Miriah should coordinate a reviewed transfer/integration of the frontend source into the intended branch, resolve the API contract against the backend, and run the combined tests. Deployment remains a separate later operational step.
