echo "Iniciando task de reload de nginx - $(date)" >>  {{ certs_directory }}/letsencrypt/logs/nginx_reload.log
sudo docker exec -it nginx bash -c "/usr/sbin/nginx -s reload" >> {{ certs_directory }}/letsencrypt/logs/nginx_reload.log 2>&1
