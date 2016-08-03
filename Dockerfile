FROM python:2.7 
RUN apt-get update && apt-get -y install curl vim
RUN pip install requests requests_unixsocket docker-py
COPY . /python/src
WORKDIR /python/src
ENTRYPOINT ["python", "main.py"]
