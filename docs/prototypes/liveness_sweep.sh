#!/usr/bin/env bash
# E3 liveness sweep: check each high-scored posting's URL is still OPEN.
# LIVE = HTTP 200 AND the final URL still points at the posting (has /jobs/ or a
# lever UUID). DEAD = 4xx/5xx, or a 200 that redirected to a board root / ?error.
UA="Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
rows=$(sudo -n docker exec docker-postgres-1 psql -U applicant -d applicant -t -A -F'|' -c \
  "SELECT id, round(viability_score*100), coalesce(source_url,''), left(regexp_replace(title,'[|]',' ','g'),44)
     FROM job_postings
    WHERE viability_score >= 0.60 AND source_url LIKE 'http%'
    ORDER BY viability_score DESC LIMIT 45")
live=0; dead=0
echo "SCORE STATUS CODE  TITLE"
while IFS='|' read -r id score url title; do
  [ -z "$url" ] && continue
  read -r code final < <(curl -s -A "$UA" -o /dev/null -w "%{http_code} %{url_effective}" -L --max-time 18 "$url" 2>/dev/null)
  if [ "$code" = "200" ] && echo "$final" | grep -qiE '/jobs/|/[0-9a-f]{8}-[0-9a-f]{4}'; then
    st="LIVE "; live=$((live+1))
  else
    st="DEAD "; dead=$((dead+1)); echo "  DEAD_ID $id"
  fi
  printf "%-5s %s %s  %s\n" "$score" "$st" "$code" "$title"
done <<< "$rows"
echo "---- LIVE=$live DEAD=$dead ----"
