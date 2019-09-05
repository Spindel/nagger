# Merge Nagger

A small Merge request nagger


1. Invite "Naggus Bottus" into your project as _reporter_
2. Create an API token for Naggus Bottus to use, and add it to the project
   under the variable name "NAGGUS_KEY"

3. Add a CI step like this:

```yaml
image: registry.gitlab.com/modioab/naggus:master
script:
- nagger nag
```

`nagger` will run on each commit, using the permissions in the NAGGUS_KEY
token, and will ensure that if there is an Merge Request open, it has a
Milestone, and comment on that.


