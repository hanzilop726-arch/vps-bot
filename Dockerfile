FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    openssh-server \
    sudo \
    bash \
    curl \
    wget \
    nano \
    vim \
    git \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /run/sshd && \
    useradd -m -s /bin/bash vpsuser && \
    echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && \
    echo 'AllowUsers root' >> /etc/ssh/sshd_config

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D", "-e"]
