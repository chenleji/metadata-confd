FROM ubuntu:14.04
COPY ./confd /bin/confd
COPY ./conf.d /etc/confd/conf.d
COPY ./templates /etc/confd/templates
RUN mkdir -p /var/lib/floatting-ip; apt-get update -y; apt-get install curl -y
#ENTRYPOINT ["confd", "-backend", "rancher" "-confdir", "/etc/confd"]

