ARG IMAGE_BUILD_FROM
FROM $IMAGE_BUILD_FROM
MAINTAINER "D.S. Ljungmark" <ljungmark@modio.se>

ARG URL=unknown
ARG COMMIT=unknown
ARG BRANCH=unknown
ARG HOST=unknown
ARG DATE=unknown

LABEL "se.modio.ci.url"=$URL "se.modio.ci.branch"=$BRANCH "se.modio.ci.commit"=$COMMIT "se.modio.ci.host"=$HOST "se.modio.ci.date"=$DATE

RUN python3 -m pip install --no-index --find-links=/build/ nagger

CMD ["/usr/local/bin/nagger"]
