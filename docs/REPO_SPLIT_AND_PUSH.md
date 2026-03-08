# Backdroply Repo Split Plan

Bu proje `infra/scripts/split-repos.ps1` ile coklu-repo yapisina ayrilir.

## Olusan Repo Klasorleri

- `C:\Users\fatih\projects\backdroply-web`
- `C:\Users\fatih\projects\backdroply-backend`
- `C:\Users\fatih\projects\backdroply-engine`
- `C:\Users\fatih\projects\backdroply-mobile`
- `C:\Users\fatih\projects\backdroply-infra`

## Yeniden Uretme

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\scripts\split-repos.ps1 -CleanTarget
```

Git repo olusturma + ilk commit:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\scripts\split-repos.ps1 -CleanTarget -InitGit -Commit -DefaultBranch main
```

## Push Oncesi

1. `-InitGit -Commit` kullanmadiysan her repo klasorunde `git init` + `git add .` + `git commit` yap.
2. GitHub repo URL'lerini `git remote add origin <url>` ile ekle.
3. `git push -u origin main` ile push et.
4. CI/CD ve secrets degerlerini repo bazinda ayarla.

Alternatif: hepsini tek komutta push etmek icin:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\scripts\push-split-repos.ps1 `
  -WebRemote https://github.com/<user>/backdroply-web.git `
  -BackendRemote https://github.com/<user>/backdroply-backend.git `
  -EngineRemote https://github.com/<user>/backdroply-engine.git `
  -MobileRemote https://github.com/<user>/backdroply-mobile.git `
  -InfraRemote https://github.com/<user>/backdroply-infra.git
```

## Not

Backend artik Flyway yerine Liquibase kullanir. Changelog:

- `src/main/resources/db/changelog/db.changelog-master.yaml`
