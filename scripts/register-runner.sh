#!/usr/bin/env bash
# S0: register a host as a self-hosted GitHub Actions runner over SSM (no SSH in this lab).
# Name and label are lab-<role> (contracts/runtime.yaml; scripts/health.sh looks for that name).
#
#   export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...   (AWS Details)
#   scripts/register-runner.sh [app|platform|llm]      (default: app)
#
# The runner runs as the host's `runner` user (in the docker group) with whatever AWS identity the
# host has. Decision point: instance profile vs static credentials for the runner. Record it in decisions/.
#
# Refuses unless fork-PR workflows need approval for all external contributors: the repo is public.
# The registration token goes to gh and SSM only, never to the terminal. It's single-use and expires
# within an hour, but it does sit in this account's SSM command history until then.
# Safe to re-run: a host that already has a runner is left alone.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

RUNNER_VERSION=2.338.2
RUNNER_SHA256=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945  # linux-arm64, from the release notes

role=${1:-app}
[[ $role =~ ^(app|platform|llm)$ ]] || { echo "usage: $0 [app|platform|llm]" >&2; exit 2; }
root="$(cd "$(dirname "$0")/.." && pwd)"

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
policy=$(gh api "repos/$repo/actions/permissions/fork-pr-contributor-approval" -q .approval_policy 2>/dev/null || echo unknown)
[[ $policy == all_external_contributors ]] || {
  echo "refusing: fork-PR approval on $repo is '$policy'. Set Settings > Actions > General >" \
    "'Require approval for all external contributors' first." >&2
  exit 1
}

instance=$(terraform -chdir="$root/infra/live" output -raw "${role}_instance_id")
ping=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$instance" \
  --query 'InstanceInformationList[0].PingStatus' --output text)
[[ $ping == Online ]] || { echo "lab-$role ($instance) isn't online in SSM yet ($ping): give it a minute after apply" >&2; exit 1; }

token=$(gh api -X POST "repos/$repo/actions/runners/registration-token" -q .token)
tarball="actions-runner-linux-arm64-$RUNNER_VERSION.tar.gz"
# Runs as root on the host. $token, $repo, $role and the pins expand here; \$ expands there.
remote=$(cat <<EOF
set -euo pipefail
test -f /var/lib/lab-setup-done || { echo "first-boot setup isn't done: see /var/log/lab-setup.log"; exit 1; }
cd /opt/actions-runner
if [ -f .runner ]; then echo "lab-$role already has a runner; to replace it: ./svc.sh uninstall, delete .runner, re-run"; exit 0; fi
curl -fsSL -o "$tarball" "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$tarball"
echo "$RUNNER_SHA256  $tarball" | sha256sum -c -
tar xzf "$tarball" && rm "$tarball"
chown -R runner:runner /opt/actions-runner
sudo -u runner ./config.sh --unattended --replace --url "https://github.com/$repo" --token "$token" \
  --name "lab-$role" --labels "lab-$role" --work _work
./svc.sh install runner
./svc.sh start
EOF
)

params=$(mktemp)
trap 'rm -f "$params"' EXIT
chmod 600 "$params"
jq -n --arg s "$remote" '{commands: [$s]}' >"$params"
cmd=$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
  --comment "register runner lab-$role" --parameters "file://$params" --query Command.CommandId --output text)
echo "registering lab-$role on $instance (SSM command $cmd)"

for _ in $(seq 60); do
  status=$(aws ssm get-command-invocation --command-id "$cmd" --instance-id "$instance" --query Status --output text 2>/dev/null || echo Pending)
  case $status in Pending | InProgress | Delayed) sleep 5 ;; *) break ;; esac
done
aws ssm get-command-invocation --command-id "$cmd" --instance-id "$instance" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text
[[ $status == Success ]] || { echo "registration $status" >&2; exit 1; }
gh api "repos/$repo/actions/runners" -q ".runners[] | select(.name == \"lab-$role\") | \"\(.name): \(.status)\""
