#!/usr/bin/env bash
# Canned verify recipes for common task types. Usage: verify_recipes.sh <type> <args...>
set -euo pipefail
case "${1:?type}" in
  pr)         # pr <repo> <num> [sha-to-check-in-main]
    repo=$2; num=$3; gh pr view "$num" --repo "$repo" --json state,mergedAt,mergeCommit --jq '"\(.state) \(.mergedAt // "-") \(.mergeCommit.oid[0:9] // "-")"'
    if [ "${4:-}" ]; then d=$(mktemp -d); git -C "$(git rev-parse --show-toplevel)/${repo##*/}" fetch -q origin main 2>/dev/null || true
      git -C "$(git rev-parse --show-toplevel)/${repo##*/}" merge-base --is-ancestor "$4" origin/main && echo "sha $4 IN main" || echo "sha $4 NOT in main (orphaned after squash-merge?)"; fi ;;
  deploy)     # deploy <ssh-host> <ctx> <ns> <name> — image on Deployment AND any *_IMAGE configmap keys
    ssh "$2" "kubectl --context=$3 -n $4 get deploy $5 -o jsonpath='{.spec.template.spec.containers[0].image}'; echo; kubectl --context=$3 -n $4 get cm -o json 2>/dev/null | python3 -c \"import sys,json; [print(cm['metadata']['name'],k,'=',v.split('/')[-1]) for cm in json.load(sys.stdin)['items'] for k,v in (cm.get('data') or {}).items() if k.endswith('_IMAGE')]\"" ;;
  cloudrun)   # cloudrun <ssh-host> <project> <service> [ENV_KEY...]
    h=$2; proj=$3; svc=$4; shift 4; ssh "$h" "gcloud run services describe $svc --project=$proj --region=us-central1 --format=json" | python3 -c "
import sys,json; s=json.load(sys.stdin); c=s['spec']['template']['spec']['containers'][0]
print('rev', s['status']['latestReadyRevisionName'], 'image', c['image'].split(':')[-1][:12])
keys=sys.argv[1:]; env={e['name']:e.get('value') for e in c.get('env',[])}
[print(k,'=',env.get(k)) for k in keys]" "$@" ;;
  flagsync)   # flagsync <owner/repo> <workflow.yml> <flag-substring> — last syncs touching the flag + anything after
    gh run list --repo "$2" --workflow "$3" --limit 15 --json createdAt,conclusion,displayTitle --jq ".[] | \"\(.createdAt[0:16]) \(.conclusion) \(.displayTitle[0:90])\"" | { grep -i "$4" || true; } ;;
  cron)       # cron — list session crons (informational; CronList is a session tool)
    echo "use the CronList tool in-session" ;;
  *) echo "types: pr deploy cloudrun flagsync cron" >&2; exit 2 ;;
esac
