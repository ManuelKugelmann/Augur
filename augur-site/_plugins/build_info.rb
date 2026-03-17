module Jekyll
  class BuildInfoGenerator < Generator
    safe true
    priority :highest

    def generate(site)
      sha = ENV['GITHUB_SHA'] || `git rev-parse --short HEAD 2>/dev/null`.strip
      sha = sha[0, 7] if sha.length > 7
      site.data['build'] = {
        'sha' => sha.empty? ? 'dev' : sha,
        'time' => site.time.strftime('%Y-%m-%d %H:%M UTC')
      }
    end
  end
end
