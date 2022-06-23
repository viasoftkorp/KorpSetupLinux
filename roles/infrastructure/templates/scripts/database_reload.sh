#!/bin/bash

services_to_reload=(Korp.Legacy.Authentication Korp.Legacy.Elt Korp.Vendas.AutomatizacaoDeFrete Korp.Integration.SolidWorks Korp.Authorization.Synchronizer)

# join de array separando por ' '
services=$(printf " %s" "${services_to_reload[@]}")
services=${services:1}

docker container restart $services
