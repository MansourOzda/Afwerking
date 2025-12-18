# Guide de déploiement sur Render (GRATUIT)

## 📋 Prérequis

1. Un compte GitHub (gratuit)
2. Un compte Render (gratuit) : https://render.com

## 🚀 Étapes de déploiement

### 1. Créer un dépôt GitHub

1. Créez un nouveau dépôt sur GitHub (https://github.com/new)
2. Nommez-le par exemple `telegram-bot-serrurier`
3. **Ne cochez PAS** "Initialize with README" (vous avez déjà les fichiers)

### 2. Uploader votre code sur GitHub

Ouvrez PowerShell dans le dossier `Documents\bot` et exécutez :

```powershell
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/VOTRE_USERNAME/telegram-bot-serrurier.git
git push -u origin main
```

*(Remplacez VOTRE_USERNAME par votre nom d'utilisateur GitHub)*

### 3. Créer un service sur Render

1. Allez sur https://dashboard.render.com
2. Cliquez sur **"New +"** → **"Background Worker"**
3. Connectez votre compte GitHub si nécessaire
4. Sélectionnez votre dépôt `telegram-bot-serrurier`
5. Configurez :
   - **Name** : `telegram-bot-serrurier` (ou autre nom)
   - **Region** : Choisissez le plus proche (Frankfurt, etc.)
   - **Branch** : `main`
   - **Root Directory** : (laissez vide)
   - **Environment** : `Python 3`
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `python Slotenbot.py`

### 4. Configurer les variables d'environnement

Dans Render, dans la section **"Environment"**, ajoutez ces variables :

- **BOT_TOKEN** : `8280174350:AAF-CpOguFGjfzl0mMpinynB2VWCRSSMFT4`
- **GROUP_ID** : `-5071208306`
- **USER_IDS** : `395799444` (ou `395799444,123456789` pour plusieurs IDs)

⚠️ **IMPORTANT** : Pour plus de sécurité, vous pouvez changer votre BOT_TOKEN depuis @BotFather avant le déploiement.

### 5. Déployer

1. Cliquez sur **"Create Background Worker"**
2. Render va installer les dépendances et lancer le bot
3. Vérifiez les logs pour confirmer que le bot démarre correctement
4. Le bot est maintenant actif 24/7 ! 🎉

## 📊 Vérifier que ça fonctionne

1. Dans Telegram, envoyez `/start` dans votre groupe
2. Vous devriez voir le menu du bot
3. Si ça ne marche pas, consultez les logs dans Render Dashboard

## 🔄 Mises à jour

Pour mettre à jour le bot :
1. Modifiez le code localement
2. Commitez et poussez sur GitHub : `git add . && git commit -m "Update" && git push`
3. Render redéploiera automatiquement

## 💾 Base de données

La base de données SQLite (`retours_intervention.db`) sera créée automatiquement sur Render.
Elle persistera entre les redéploiements sur le système de fichiers de Render.

## 🆓 Limitations du plan gratuit

- Le service peut s'endormir après 15 minutes d'inactivité (mais se réveille automatiquement)
- Peut prendre quelques secondes à démarrer si endormi
- Parfait pour un bot Telegram qui reçoit des messages

## 🆘 En cas de problème

Consultez les logs dans Render Dashboard → Votre service → Logs

