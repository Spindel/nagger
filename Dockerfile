FROM registry.gitlab.com/modioab/base-image/fedora-31/python:master
MAINTAINER "D.S. Ljungmark" <ljungmark@modio.se>

ARG URL=unknown
ARG COMMIT=unknown
ARG BRANCH=unknown
ARG HOST=unknown
ARG DATE=unknown

LABEL "se.modio.ci.url"=$URL "se.modio.ci.branch"=$BRANCH "se.modio.ci.commit"=$COMMIT "se.modio.ci.host"=$HOST "se.modio.ci.date"=$DATE

ADD nagger.tar /
RUN cd /srv/app && pip install .
CMD ["/usr/local/bin/nagger"]
