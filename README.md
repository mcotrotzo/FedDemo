docker build -t batterypv-example .

1. Deploy Twins
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example deploy:twins
2. Deploy Simulator
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example deploy:simulator
3. Deploy FedTwin
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example deploy:fedTwin

* Destroy
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example destroy
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example destroy:fedTwin
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example destroy:simulator
docker run -it -v //var/run/docker.sock:/var/run/docker.sock batterypv-example destroy:twins
