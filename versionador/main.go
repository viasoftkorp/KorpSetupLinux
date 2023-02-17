package main

import (
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"
)

/*
	cd .\versionador
	.\versionador.exe -versaoAnterior="2022.3.0" -novaVersao="2022.4.0" -caminho="..\\roles"
*/
type OpcoesVersionador struct {
	VersaoAnterior string
	VersaoSeguinte string
	Caminho        string
	Sobrescrever   bool
}

func main() {
	opcoes := pegarArgumentos()

	diretorioRoles, err := os.ReadDir(opcoes.Caminho)
	if err != nil {
		log.Fatalf("problema ao listar diretórios de diretorioRoles: %v", err)
	}

	for _, diretorioRole := range diretorioRoles {
		if diretorioRole.IsDir() {
			info, err := diretorioRole.Info()
			if err != nil {
				log.Fatalf("problema ao listar info do diretório %s: %v de diretorioRoles", diretorioRole.Name(), err)
			}

			if err = gerarNovaVersao(opcoes, info); err != nil {
				log.Fatalf("problema ao gerar arquivos da versão %s: %v", opcoes.VersaoSeguinte, err)
			}
		}
	}
}

func gerarNovaVersao(opcoes *OpcoesVersionador, info fs.FileInfo) error {
	role := info.Name()
	diretorioComposesVersaoAnterior := filepath.Join(opcoes.Caminho, role, "templates", "composes", opcoes.VersaoAnterior)
	_, err := os.Stat(diretorioComposesVersaoAnterior)
	if err != nil {
		//a role não é versionada
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}

	diretorioComposesVersaoSeguinte := filepath.Join(opcoes.Caminho, role, "templates", "composes", opcoes.VersaoSeguinte)
	_, err = os.Stat(diretorioComposesVersaoSeguinte)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return err
		}

		if err = os.MkdirAll(diretorioComposesVersaoSeguinte, os.ModePerm); err != nil {
			return err
		}
	}

	arquivoComposeRole := fmt.Sprintf("%s-compose.yml.j2", role)

	caminhoComposeJinjaVersaoSeguinte := filepath.Join(diretorioComposesVersaoSeguinte, arquivoComposeRole)
	_, err = os.Stat(caminhoComposeJinjaVersaoSeguinte)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return err
		}
	} else if !opcoes.Sobrescrever {
		return nil
	}

	caminhoComposeJinjaVersaoAnterior := filepath.Join(diretorioComposesVersaoAnterior, arquivoComposeRole)
	composeVersaoAnteriorBytes, err := os.ReadFile(caminhoComposeJinjaVersaoAnterior)
	if err != nil {
		return err
	}

	composeVersaoAnteriorStr := string(composeVersaoAnteriorBytes)

	//a mudança entre uma versão e outra é simples, basicamente temos que fazer o replace da versão, uma vez com "-" e outra com "."
	compsoeVersaoSeguinteStr := strings.ReplaceAll(composeVersaoAnteriorStr, opcoes.VersaoAnterior, opcoes.VersaoSeguinte)
	compsoeVersaoSeguinteStr = strings.ReplaceAll(compsoeVersaoSeguinteStr, strings.ReplaceAll(opcoes.VersaoAnterior, ".", "-"),
		strings.ReplaceAll(opcoes.VersaoSeguinte, ".", "-"))

	err = os.WriteFile(caminhoComposeJinjaVersaoSeguinte, []byte(compsoeVersaoSeguinteStr), os.ModePerm)

	return err
}

func pegarArgumentos() *OpcoesVersionador {
	versaoAnteriorPtr := flag.String("versaoAnterior", "", "a versão que será utilizada como base")
	versaoSeguintePtr := flag.String("novaVersao", "", "a nova versão")
	caminhoPtr := flag.String("caminho", "..\\roles", "a pasta das roles")
	sobrescreverPtr := flag.Bool("sobrescrever", false, "indica se deve sobrescrever o compose ")

	flag.Parse()

	versaoAnterior := *versaoAnteriorPtr
	versaoSeguinte := *versaoSeguintePtr
	caminho := *caminhoPtr
	sobrescrever := *sobrescreverPtr

	if strings.TrimSpace(versaoAnterior) == "" || strings.TrimSpace(versaoSeguinte) == "" || strings.TrimSpace(caminho) == "" {
		log.Fatalf("versaoAnterior/novaVersao/caminho não foram passados por argumento")
	}

	_, err := os.Stat(caminho)
	if err != nil && os.IsNotExist(err) {
		log.Fatalf("caminho da linha de comando não é válido")
	}

	return &OpcoesVersionador{
		VersaoAnterior: versaoAnterior,
		VersaoSeguinte: versaoSeguinte,
		Caminho:        caminho,
		Sobrescrever:   sobrescrever,
	}
}
